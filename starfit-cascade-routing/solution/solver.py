#!/usr/bin/env python3
"""Reference solution for the multi-reservoir network simulation with losses.

Reads domain parameters, network topology, and forcing from JSON/CSV files.
Implements the operating rules and physical loss processes documented in
the reference implementation. Writes daily results to CSV.
"""


import csv
import json
import math
import os
from collections import deque
from datetime import date, timedelta


def load_params():
    with open('/app/domain/params.json') as f:
        data = json.load(f)

    reservoirs = data['reservoirs']

    # Build adjacency from edge list
    upstream_of = {r['id']: [] for r in reservoirs}
    for edge in data['edges']:
        upstream_of[edge['downstream']].append(edge['upstream'])

    return {
        'start_date': data['start_date'],
        'num_days': data['num_days'],
        'dt_seconds': data['dt_seconds'],
        'reservoirs': reservoirs,
        'upstream_of': upstream_of,
    }


def load_forcing():
    rows = []
    with open('/app/domain/forcing.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'day': int(row['day']),
                1: float(row['reservoir_1_local_inflow_cms']),
                2: float(row['reservoir_2_local_inflow_cms']),
                3: float(row['reservoir_3_local_inflow_cms']),
                4: float(row['reservoir_4_local_inflow_cms']),
                'pet': float(row['pet_mm_per_day']),
            })
    return rows


def topological_sort(reservoirs, upstream_of):
    """Kahn's algorithm: upstream reservoirs processed first."""
    id_to_res = {r['id']: r for r in reservoirs}
    in_degree = {r['id']: len(upstream_of[r['id']]) for r in reservoirs}

    # Forward edges: who does each reservoir feed?
    feeds = {r['id']: [] for r in reservoirs}
    for rid, upstreams in upstream_of.items():
        for u in upstreams:
            feeds[u].append(rid)

    queue = deque(rid for rid, deg in in_degree.items() if deg == 0)
    order = []

    while queue:
        rid = queue.popleft()
        order.append(rid)
        for downstream_id in feeds[rid]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                queue.append(downstream_id)

    return [id_to_res[rid] for rid in order]


def compute_nor(epiweek, nor_params):
    theta = 2.0 * math.pi * epiweek / 52.0 - nor_params['phase']
    raw = nor_params['amplitude'] * math.cos(theta) + nor_params['offset']
    return max(nor_params['floor'], min(nor_params['ceiling'], raw))


def compute_release(storage, capacity, nor_hi, nor_lo, mean_flow, rp):
    s_norm = storage / capacity
    if s_norm > nor_hi:
        d = s_norm - nor_hi
        rate = rp['flood_max'] * (
            rp['flood_scale'] * d ** rp['flood_exp'] + rp['flood_base']
        )
    elif s_norm < nor_lo:
        d = nor_lo - s_norm
        rate = rp['conserve_min'] * (
            rp['conserve_scale'] * d ** rp['conserve_exp'] + rp['conserve_base']
        )
    else:
        rate = rp['normal_coeff']
    return max(0.0, rate * mean_flow)


def run():
    params = load_params()
    forcing = load_forcing()

    start_date = date.fromisoformat(params['start_date'])
    dt = float(params['dt_seconds'])
    reservoirs = params['reservoirs']
    upstream_of = params['upstream_of']

    sorted_reservoirs = topological_sort(reservoirs, upstream_of)

    storages = {r['id']: r['initial_storage_mcm'] for r in reservoirs}

    fieldnames = ['day', 'date']
    for i in range(1, len(reservoirs) + 1):
        pfx = f'r{i}'
        fieldnames.extend([
            f'{pfx}_inflow', f'{pfx}_storage', f'{pfx}_release',
            f'{pfx}_spill', f'{pfx}_outflow', f'{pfx}_evap',
            f'{pfx}_seepage', f'{pfx}_nor_hi', f'{pfx}_nor_lo',
        ])

    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/simulation.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for frow in forcing:
            d = frow['day']
            current = start_date + timedelta(days=d)
            epiweek = current.isocalendar()[1]
            pet_mm = frow['pet']

            row = {'day': d, 'date': current.isoformat()}
            outflows = {}

            for res in sorted_reservoirs:
                rid = res['id']
                pfx = f'r{rid}'
                s_old = storages[rid]
                capacity = res['capacity_mcm']
                mean_flow = res['mean_inflow_cms']

                # Total inflow = local + sum of upstream outflows
                inflow = frow[rid]
                for upstream_id in upstream_of[rid]:
                    inflow += outflows[upstream_id]

                # Step 1: Evaporation from beginning-of-step storage
                area_km2 = res['area_coeff'] * s_old ** res['area_exp']
                adjusted_pet = pet_mm * res['pet_adjustment']
                evap_mcm = area_km2 * adjusted_pet * 1e-3

                # Step 2: Seepage from beginning-of-step storage
                seepage_mcm = res['seepage_rate'] * s_old

                # Step 3: Apply losses before release computation
                s_post_loss = s_old - evap_mcm - seepage_mcm

                # Step 4: NOR bounds
                nor_hi = compute_nor(epiweek, res['nor_hi'])
                nor_lo = compute_nor(epiweek, res['nor_lo'])

                # Step 5: Release from post-loss storage
                release = compute_release(
                    s_post_loss, capacity, nor_hi, nor_lo,
                    mean_flow, res['release']
                )

                # Step 6: Volume balance
                s_new = s_post_loss + (inflow - release) * dt / 1e6

                spill = 0.0
                if s_new > capacity:
                    spill = (s_new - capacity) * 1e6 / dt
                    s_new = capacity
                elif s_new < 0.0:
                    release += s_new * 1e6 / dt
                    release = max(0.0, release)
                    s_new = 0.0

                outflow = release + spill
                evap_cms = evap_mcm * 1e6 / dt
                seepage_cms = seepage_mcm * 1e6 / dt

                row[f'{pfx}_inflow'] = inflow
                row[f'{pfx}_storage'] = s_new
                row[f'{pfx}_release'] = release
                row[f'{pfx}_spill'] = spill
                row[f'{pfx}_outflow'] = outflow
                row[f'{pfx}_evap'] = evap_cms
                row[f'{pfx}_seepage'] = seepage_cms
                row[f'{pfx}_nor_hi'] = nor_hi
                row[f'{pfx}_nor_lo'] = nor_lo

                storages[rid] = s_new
                outflows[rid] = outflow

            writer.writerow(row)

    print(f'Wrote {len(forcing)} rows to /app/results/simulation.csv')


if __name__ == '__main__':
    run()
