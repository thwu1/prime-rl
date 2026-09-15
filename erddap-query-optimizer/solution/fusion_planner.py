#!/usr/bin/env python3
"""ERDDAP Multi-Source Data Fusion Planner.

"""

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path


# ======== DAS Parser ========

def parse_das(filepath):
    """Parse an ERDDAP DAS file into dict of variable_name -> {attr: value}."""
    with open(filepath) as f:
        content = f.read()

    result = {}
    stack = []
    current_attrs = None

    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.endswith('{'):
            name = stripped[:-1].strip()
            if name == 'Attributes':
                continue
            stack.append(name)
            if name != 's':
                result[name] = {}
                current_attrs = result[name]
            else:
                current_attrs = None
            continue

        if stripped == '}':
            if stack:
                stack.pop()
                current_attrs = None
                for s in reversed(stack):
                    if s != 's' and s in result:
                        current_attrs = result[s]
                        break
            continue

        if current_attrs is not None and stripped.endswith(';'):
            attr_line = stripped[:-1].strip()
            parts = attr_line.split(None, 2)
            if len(parts) >= 3:
                dtype, key, value = parts
                if dtype == 'String':
                    current_attrs[key] = value.strip('"')
                elif dtype in ('Float64', 'Float32'):
                    vals = [v.strip() for v in value.split(',')]
                    if len(vals) == 1:
                        try:
                            current_attrs[key] = float(vals[0])
                        except ValueError:
                            pass
                    else:
                        try:
                            current_attrs[key] = [float(v) for v in vals]
                        except ValueError:
                            pass
                elif dtype in ('Int32', 'Int16', 'Int64'):
                    try:
                        current_attrs[key] = int(value)
                    except ValueError:
                        pass

    return result


def parse_dds(filepath):
    """Parse DDS file for dataset type, dimensions, and variables."""
    with open(filepath) as f:
        content = f.read()

    result = {'type': None, 'dimensions': [], 'variables': []}

    if 'GRID' in content:
        result['type'] = 'grid'
        array_match = re.search(
            r'ARRAY:\s*\n\s+\w+\s+(\w+)((?:\[\w+\s*=\s*\d+\])+)', content)
        if array_match:
            dims_str = array_match.group(2)
            for dim_match in re.finditer(r'\[(\w+)\s*=\s*\d+\]', dims_str):
                dim_name = dim_match.group(1)
                if dim_name not in result['dimensions']:
                    result['dimensions'].append(dim_name)
        for m in re.finditer(r'^\s+\}\s+(\w+)\s*;', content, re.MULTILINE):
            vname = m.group(1)
            if vname not in result['variables']:
                result['variables'].append(vname)
    elif 'Sequence' in content:
        result['type'] = 'table'
        seq_match = re.search(
            r'Sequence\s*\{(.*?)\}\s*s;', content, re.DOTALL)
        if seq_match:
            for var_match in re.finditer(r'(\w+)\s+(\w+);', seq_match.group(1)):
                result['variables'].append(var_match.group(2))

    return result


# ======== Dataset Loading ========

def load_datasets(metadata_dir, registry):
    """Load all dataset metadata from DAS/DDS files."""
    datasets = {}

    for das_path in sorted(Path(metadata_dir).glob('*.das')):
        ds_id = das_path.stem
        if ds_id not in registry['datasets']:
            continue
        dds_path = das_path.with_suffix('.dds')
        if not dds_path.exists():
            continue

        das = parse_das(str(das_path))
        dds = parse_dds(str(dds_path))

        nc_global = das.get('NC_GLOBAL', {})
        lon_min = nc_global.get('geospatial_lon_min', 0)
        lon_convention = '-180/180' if lon_min < 0 else '0-360'

        ds = {
            'datasetID': ds_id,
            'type': dds['type'],
            'baseUrl': registry['datasets'][ds_id]['server'],
            'lonConvention': lon_convention,
            'das': das,
            'dds': dds,
        }

        if dds['type'] == 'grid':
            dims = []
            for dim_name in dds['dimensions']:
                dim_attrs = das.get(dim_name, {})
                dim_info = {'name': dim_name}
                if dim_name == 'time':
                    dim_info['type'] = 'temporal'
                    dim_info['spacing'] = dim_attrs.get('spacing')
                elif dim_name in ('altitude', 'zlev', 'depth'):
                    dim_info['type'] = 'vertical'
                    actual_range = dim_attrs.get('actual_range', [0.0, 0.0])
                    if isinstance(actual_range, list):
                        dim_info['values'] = [actual_range[0]]
                    else:
                        dim_info['values'] = [actual_range]
                elif dim_name in ('latitude', 'longitude'):
                    dim_info['type'] = 'spatial'
                    actual_range = dim_attrs.get('actual_range', [0.0, 0.0])
                    if isinstance(actual_range, list):
                        dim_info['start'] = actual_range[0]
                        dim_info['stop'] = actual_range[1]
                    dim_info['spacing'] = dim_attrs.get('spacing', 1.0)
                dims.append(dim_info)
            ds['dimensions'] = dims

        ds['lat_range'] = [
            nc_global.get('geospatial_lat_min', -90.0),
            nc_global.get('geospatial_lat_max', 90.0)
        ]
        ds['lon_range'] = [
            nc_global.get('geospatial_lon_min',
                          0.0 if lon_convention == '0-360' else -180.0),
            nc_global.get('geospatial_lon_max',
                          360.0 if lon_convention == '0-360' else 180.0)
        ]

        datasets[ds_id] = ds

    return datasets


# ======== Coordinate Helpers ========

def convert_lon(lon, from_conv, to_conv):
    """Convert a longitude value between conventions."""
    if from_conv == to_conv:
        return lon
    if from_conv == '0-360' and to_conv == '-180/180':
        return lon - 360.0 if lon > 180.0 else lon
    if from_conv == '-180/180' and to_conv == '0-360':
        return lon + 360.0 if lon < 0.0 else lon
    return lon


def get_dim(ds, dim_name):
    """Get dimension info by name from a dataset."""
    for dim in ds.get('dimensions', []):
        if dim['name'] == dim_name:
            return dim
    return None


def compute_stride(target_res, source_spacing):
    """Calculate subsampling stride from target/source resolution ratio."""
    if target_res is None:
        return 1
    return max(1, round(target_res / source_spacing))


# ======== CF Conventions Helpers ========

def get_ancillary_variables(das, var_name):
    """Get ancillary variable names from CF ancillary_variables attribute."""
    var_attrs = das.get(var_name, {})
    anc_str = var_attrs.get('ancillary_variables', '')
    if not anc_str:
        return []
    return anc_str.split()


def get_standard_name(das, var_name):
    """Get CF standard_name for a variable."""
    var_attrs = das.get(var_name, {})
    return var_attrs.get('standard_name', '')


def get_units(das, var_name):
    """Get units for a variable."""
    var_attrs = das.get(var_name, {})
    return var_attrs.get('units', '')


def compute_unit_conversion(source_unit, target_unit):
    """Compute conversion factors: target = source * scale + offset."""
    if source_unit == target_unit:
        return None
    if source_unit == 'kelvin' and target_unit == 'degree_C':
        return (1.0, -273.15)
    if source_unit == 'degree_C' and target_unit == 'kelvin':
        return (1.0, 273.15)
    return None


# ======== Spatial Coverage ========

def compute_spatial_coverage(ds, query_lat, query_lon, query_lon_conv):
    """Compute spatial coverage fractions for a dataset vs query region."""
    ds_lat = ds['lat_range']

    lat_overlap_min = max(query_lat[0], ds_lat[0])
    lat_overlap_max = min(query_lat[1], ds_lat[1])
    lat_overlap = max(0.0, lat_overlap_max - lat_overlap_min)
    lat_query_range = query_lat[1] - query_lat[0]
    lat_frac = lat_overlap / lat_query_range if lat_query_range > 0 else 1.0

    ds_lon = ds['lon_range']
    ds_lon_conv = ds['lonConvention']

    q_lon_start = convert_lon(query_lon[0], query_lon_conv, ds_lon_conv)
    q_lon_stop = convert_lon(query_lon[1], query_lon_conv, ds_lon_conv)

    if q_lon_start <= q_lon_stop:
        lon_overlap_min = max(q_lon_start, ds_lon[0])
        lon_overlap_max = min(q_lon_stop, ds_lon[1])
        lon_overlap = max(0.0, lon_overlap_max - lon_overlap_min)
        lon_query_range = q_lon_stop - q_lon_start
    else:
        if ds_lon_conv == '0-360':
            lon_query_range = (360.0 - q_lon_start) + q_lon_stop
        else:
            lon_query_range = (180.0 - q_lon_start) + (q_lon_stop + 180.0)
        ds_lon_range = ds_lon[1] - ds_lon[0]
        if ds_lon_range >= 350:
            lon_overlap = lon_query_range
        else:
            part1 = max(0.0, ds_lon[1] - max(q_lon_start, ds_lon[0]))
            part2 = max(0.0, min(q_lon_stop, ds_lon[1]) - ds_lon[0])
            lon_overlap = part1 + part2

    lon_frac = min(1.0, lon_overlap / lon_query_range if lon_query_range > 0 else 1.0)

    return {
        'latitude_fraction': round(lat_frac, 6),
        'longitude_fraction': round(lon_frac, 6)
    }


# ======== URL Building ========

def build_griddap_dim_constraint(start, stop, stride, single_value=None):
    """Build a griddap dimension constraint bracket."""
    if single_value is not None:
        return f'[({single_value})]'
    return f'[({start}):{stride}:({stop})]'


def build_griddap_url(base_url, dataset_id, variables, dim_constraints):
    """Build a complete griddap URL."""
    var_parts = [var + ''.join(dim_constraints) for var in variables]
    return f'{base_url}/griddap/{dataset_id}.csv?{",".join(var_parts)}'


def build_tabledap_url(base_url, dataset_id, variables, filter_constraints):
    """Build a complete tabledap URL."""
    var_str = ','.join(variables)
    constraint_str = '&'.join(filter_constraints)
    return f'{base_url}/tabledap/{dataset_id}.csv?{var_str}&{constraint_str}'


# ======== Temporal Alignment ========

RESOLUTION_LABELS = {
    86400.0: 'daily',
    691200.0: '8-day',
    2592000.0: 'monthly',
}


def get_temporal_info(ds):
    """Get temporal resolution info for a dataset."""
    if ds['type'] == 'table':
        return {'resolution_seconds': None, 'resolution_label': 'irregular'}

    time_dim = get_dim(ds, 'time')
    if time_dim and time_dim.get('spacing') is not None:
        spacing = time_dim['spacing']
        label = RESOLUTION_LABELS.get(spacing, f'{int(spacing)}s')
        return {'resolution_seconds': spacing, 'resolution_label': label}

    return {'resolution_seconds': None, 'resolution_label': 'unknown'}


# ======== Unit Harmonization ========

def determine_unit_targets(datasets, query_requests):
    """Determine target units for each standard_name across datasets in a query."""
    sn_units = {}

    for req in query_requests:
        ds_id = req['datasetID']
        ds = datasets[ds_id]
        das = ds['das']

        for var in req['variables']:
            sn = get_standard_name(das, var)
            if sn:
                unit = get_units(das, var)
                if sn not in sn_units:
                    sn_units[sn] = []
                sn_units[sn].append((ds_id, var, unit))

    targets = {}
    for sn, entries in sn_units.items():
        if len(entries) < 2:
            continue
        units = [e[2] for e in entries]
        unique_units = set(units)
        if len(unique_units) <= 1:
            continue

        counter = Counter(units)
        max_count = max(counter.values())
        candidates = [u for u, c in counter.items() if c == max_count]
        if 'degree_C' in candidates:
            target = 'degree_C'
        elif 'kelvin' in candidates:
            target = 'kelvin'
        else:
            target = sorted(candidates)[0]

        targets[sn] = target

    return targets


# ======== Main Processing ========

def process_griddap(ds, query, request, unit_targets):
    """Generate query plan for a griddap (gridded) dataset."""
    query_lon_conv = query['region']['lonConvention']
    ds_lon_conv = ds['lonConvention']
    lat_range = query['region']['latitude']
    lon_range = query['region']['longitude']
    time_range = query.get('time')
    target_res = request.get('targetResolution')
    variables = request['variables']
    das = ds['das']

    lon_start = convert_lon(lon_range[0], query_lon_conv, ds_lon_conv)
    lon_stop = convert_lon(lon_range[1], query_lon_conv, ds_lon_conv)
    antimeridian_split = (lon_start > lon_stop)

    lon_dim = get_dim(ds, 'longitude')
    lat_dim = get_dim(ds, 'latitude')

    lat_stride = compute_stride(target_res, lat_dim['spacing'])
    lon_stride = compute_stride(target_res, lon_dim['spacing'])

    vert_dim = None
    for dim in ds.get('dimensions', []):
        if dim['type'] == 'vertical':
            vert_dim = dim
            break

    if antimeridian_split:
        lon_ranges = [
            {'start': lon_dim['start'], 'stop': lon_stop, 'stride': lon_stride},
            {'start': lon_start, 'stop': lon_dim['stop'], 'stride': lon_stride},
        ]
    else:
        lon_ranges = [
            {'start': lon_start, 'stop': lon_stop, 'stride': lon_stride}
        ]

    all_ancillary = []
    for var in variables:
        anc = get_ancillary_variables(das, var)
        dds_vars = ds['dds']['variables']
        for a in anc:
            if a in dds_vars and a not in all_ancillary:
                all_ancillary.append(a)

    url_variables = list(variables) + all_ancillary

    urls = []
    dim_order = ds['dds']['dimensions']

    for lr in lon_ranges:
        dim_constraints = []
        for dim_name in dim_order:
            if dim_name == 'time' and time_range:
                dim_constraints.append(
                    build_griddap_dim_constraint(
                        time_range['start'], time_range['stop'], 1))
            elif dim_name in ('altitude', 'zlev', 'depth') and vert_dim:
                dim_constraints.append(
                    build_griddap_dim_constraint(
                        None, None, 1, single_value=vert_dim['values'][0]))
            elif dim_name == 'latitude':
                dim_constraints.append(
                    build_griddap_dim_constraint(
                        lat_range[0], lat_range[1], lat_stride))
            elif dim_name == 'longitude':
                dim_constraints.append(
                    build_griddap_dim_constraint(
                        lr['start'], lr['stop'], lr['stride']))

        urls.append(build_griddap_url(
            ds['baseUrl'], ds['datasetID'], url_variables, dim_constraints))

    unit_convs = {}
    for var in variables:
        sn = get_standard_name(das, var)
        if sn and sn in unit_targets:
            source_unit = get_units(das, var)
            target_unit = unit_targets[sn]
            conv = compute_unit_conversion(source_unit, target_unit)
            if conv:
                unit_convs[var] = {
                    'source_unit': source_unit,
                    'target_unit': target_unit,
                    'scale': conv[0],
                    'offset': conv[1],
                }

    spatial_cov = compute_spatial_coverage(
        ds, lat_range, lon_range, query_lon_conv)

    result = {
        'dataset_id': ds['datasetID'],
        'server': ds['baseUrl'],
        'query_type': 'griddap',
        'variables': variables,
        'ancillary_variables': all_ancillary,
        'urls': urls,
        'antimeridian_split': antimeridian_split,
        'constraints': {
            'latitude': {
                'start': lat_range[0], 'stop': lat_range[1],
                'stride': lat_stride},
            'longitude': lon_ranges,
        },
        'unit_conversions': unit_convs,
        'spatial_coverage': spatial_cov,
    }

    if time_range:
        result['constraints']['time'] = {
            'start': time_range['start'],
            'stop': time_range['stop'],
            'stride': 1,
        }

    if vert_dim:
        result['constraints'][vert_dim['name']] = {
            'value': vert_dim['values'][0]}

    return result


def process_tabledap(ds, query, request, unit_targets):
    """Generate query plan for a tabledap (tabular) dataset."""
    query_lon_conv = query['region']['lonConvention']
    ds_lon_conv = ds['lonConvention']
    lat_range = query['region']['latitude']
    lon_range = query['region']['longitude']
    time_range = query.get('time')
    variables = request['variables']
    das = ds['das']

    lon_start = convert_lon(lon_range[0], query_lon_conv, ds_lon_conv)
    lon_stop = convert_lon(lon_range[1], query_lon_conv, ds_lon_conv)
    antimeridian_split = (lon_start > lon_stop)

    if antimeridian_split:
        if ds_lon_conv == '-180/180':
            lon_ranges = [
                {'start': lon_start, 'stop': 180.0},
                {'start': -180.0, 'stop': lon_stop},
            ]
        else:
            lon_ranges = [
                {'start': 0.0, 'stop': lon_stop},
                {'start': lon_start, 'stop': 360.0},
            ]
    else:
        lon_ranges = [{'start': lon_start, 'stop': lon_stop}]

    all_ancillary = []
    for var in variables:
        anc = get_ancillary_variables(das, var)
        dds_vars = ds['dds']['variables']
        for a in anc:
            if a in dds_vars and a not in all_ancillary:
                all_ancillary.append(a)

    url_variables = list(variables) + all_ancillary

    urls = []
    for lr in lon_ranges:
        filters = []
        if time_range:
            filters.append(f"time>={time_range['start']}")
            filters.append(f"time<={time_range['stop']}")
        filters.append(f'latitude>={lat_range[0]}')
        filters.append(f'latitude<={lat_range[1]}')
        filters.append(f"longitude>={lr['start']}")
        filters.append(f"longitude<={lr['stop']}")
        urls.append(build_tabledap_url(
            ds['baseUrl'], ds['datasetID'], url_variables, filters))

    unit_convs = {}
    for var in variables:
        sn = get_standard_name(das, var)
        if sn and sn in unit_targets:
            source_unit = get_units(das, var)
            target_unit = unit_targets[sn]
            conv = compute_unit_conversion(source_unit, target_unit)
            if conv:
                unit_convs[var] = {
                    'source_unit': source_unit,
                    'target_unit': target_unit,
                    'scale': conv[0],
                    'offset': conv[1],
                }

    spatial_cov = compute_spatial_coverage(
        ds, lat_range, lon_range, query_lon_conv)

    result = {
        'dataset_id': ds['datasetID'],
        'server': ds['baseUrl'],
        'query_type': 'tabledap',
        'variables': variables,
        'ancillary_variables': all_ancillary,
        'urls': urls,
        'antimeridian_split': antimeridian_split,
        'constraints': {
            'latitude': {'start': lat_range[0], 'stop': lat_range[1]},
            'longitude': lon_ranges,
        },
        'unit_conversions': unit_convs,
        'spatial_coverage': spatial_cov,
    }

    if time_range:
        result['constraints']['time'] = {
            'start': time_range['start'],
            'stop': time_range['stop'],
        }

    return result


def main():
    with open('/app/server_registry.json') as f:
        registry = json.load(f)

    datasets = load_datasets('/app/metadata', registry)
    print(f'Loaded {len(datasets)} datasets: {list(datasets.keys())}', file=sys.stderr)

    with open('/app/queries.json') as f:
        queries = json.load(f)

    output = {}
    for query in queries:
        qid = query['id']

        unit_targets = determine_unit_targets(datasets, query['requests'])

        subqueries = []
        for req in query['requests']:
            ds = datasets[req['datasetID']]
            if ds['type'] == 'grid':
                subqueries.append(
                    process_griddap(ds, query, req, unit_targets))
            elif ds['type'] == 'table':
                subqueries.append(
                    process_tabledap(ds, query, req, unit_targets))

        temp_alignment = {}
        for req in query['requests']:
            ds = datasets[req['datasetID']]
            temp_alignment[req['datasetID']] = get_temporal_info(ds)

        output[qid] = {
            'subqueries': subqueries,
            'temporal_alignment': temp_alignment,
            'unit_harmonization_target': unit_targets,
        }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/fusion_plan.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('Fusion plan written to /app/output/fusion_plan.json')


if __name__ == '__main__':
    main()
