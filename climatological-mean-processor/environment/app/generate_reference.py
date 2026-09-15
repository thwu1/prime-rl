"""Generate reference output for the climate pipeline task.

Uses the correct implementation to process all field data files and
produce reference_output.json. This ensures the reference is always
consistent with the correct algorithm, regardless of floating-point
variations across environments.
"""

import json
import math
import os


def compute_area_weights(lat_bounds, lon_bounds):
    weights = []
    for lb in lat_bounds:
        row = []
        delta_sin = abs(math.sin(math.radians(lb[1])) - math.sin(math.radians(lb[0])))
        for lonb in lon_bounds:
            dlon = math.radians(abs(lonb[1] - lonb[0]))
            row.append(delta_sin * dlon)
        weights.append(row)
    return weights


def get_month_info(t, ref_year):
    return (ref_year + t // 12, (t % 12) + 1)


def get_day_counts(time_bounds, calendar, reference_year, n_months):
    return [float(time_bounds[t][1] - time_bounds[t][0]) for t in range(n_months)]


def assign_seasons(n_months, ref_year):
    SMAP = {12: 'DJF', 1: 'DJF', 2: 'DJF',
            3: 'MAM', 4: 'MAM', 5: 'MAM',
            6: 'JJA', 7: 'JJA', 8: 'JJA',
            9: 'SON', 10: 'SON', 11: 'SON'}
    seasons = {}
    for t in range(n_months):
        yr, mo = get_month_info(t, ref_year)
        sn = SMAP[mo]
        sy = yr + 1 if mo == 12 else yr
        key = (sy, sn)
        seasons.setdefault(key, []).append(t)
    return {k: v for k, v in seasons.items() if len(v) == 3}


def collapse_weighted(data, indices, day_counts):
    nlat, nlon = len(data[0]), len(data[0][0])
    td = sum(day_counts[i] for i in indices)
    result = [[0.0] * nlon for _ in range(nlat)]
    for idx in indices:
        w = day_counts[idx] / td
        for i in range(nlat):
            for j in range(nlon):
                result[i][j] += w * data[idx][i][j]
    return result


def climatological_mean(data, seasons, day_counts):
    by_season = {}
    for (yr, sn), idx in seasons.items():
        by_season.setdefault(sn, []).append(idx)
    result = {}
    for sn, instances in by_season.items():
        nlat, nlon = len(data[0]), len(data[0][0])
        ymeans = [collapse_weighted(data, idx, day_counts) for idx in instances]
        n = len(ymeans)
        clim = [[0.0] * nlon for _ in range(nlat)]
        for ym in ymeans:
            for i in range(nlat):
                for j in range(nlon):
                    clim[i][j] += ym[i][j] / n
        result[sn] = clim
    return result


def area_weighted_mean(f2d, w):
    tw, ws = 0.0, 0.0
    for i in range(len(f2d)):
        for j in range(len(f2d[0])):
            tw += w[i][j]
            ws += w[i][j] * f2d[i][j]
    return ws / tw


def process_field(filepath):
    with open(filepath) as f:
        field = json.load(f)
    data = field['data']
    lat_b = field['coordinates']['latitude']['bounds']
    lon_b = field['coordinates']['longitude']['bounds']
    time_b = field['coordinates']['time']['bounds']
    cal = field['coordinates']['time'].get('calendar', 'standard')
    ref_yr = field['reference_year']
    n = field['n_months']

    weights = compute_area_weights(lat_b, lon_b)
    dc = get_day_counts(time_b, cal, ref_yr, n)
    seasons = assign_seasons(n, ref_yr)
    clim = climatological_mean(data, seasons, dc)

    gm = {sn: area_weighted_mean(c, weights) for sn, c in clim.items()}
    su = {}
    for yr, sn in seasons:
        su.setdefault(sn, []).append(yr)
    for sn in su:
        su[sn] = sorted(set(su[sn]))

    return {'clim': clim, 'gm': gm, 'su': su, 'aw': weights}


def main():
    ref = {}
    total_aw = None

    for cal, fname in [('standard', 'field_standard'),
                       ('360_day', 'field_360day'),
                       ('noleap', 'field_noleap')]:
        r = process_field(f'/app/data/{fname}.json')
        ref[fname] = {
            'global_means': r['gm'],
            'climatology_0_0': {sn: r['clim'][sn][0][0] for sn in r['clim']},
            'seasons_used': r['su'],
        }
        if total_aw is None:
            total_aw = sum(r['aw'][i][j]
                           for i in range(len(r['aw']))
                           for j in range(len(r['aw'][0])))

    output = {
        'description': 'Reference output generated from correct implementation.',
        **ref,
        'area_weights': {'total_sum': total_aw},
    }

    with open('/app/data/reference_output.json', 'w') as f:
        json.dump(output, f, indent=2)
    print('Generated reference_output.json')


if __name__ == '__main__':
    main()
