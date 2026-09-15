#!/usr/bin/env python3
"""ERDDAP Cross-Dataset Query Federation Engine.


Parses ERDDAP DAS/DDS metadata, reads query specs, and generates
federated query plans with correct REST API URLs.
"""

import json
import os
import re
from pathlib import Path


def parse_das(filepath):
    """Parse an ERDDAP DAS metadata file into a dict of variable attributes."""
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
                popped = stack.pop()
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
                        current_attrs[key] = float(vals[0])
                    else:
                        current_attrs[key] = [float(v) for v in vals]
                elif dtype in ('Int32', 'Int16', 'Int64'):
                    current_attrs[key] = int(value)

    return result


def parse_dds(filepath):
    """Parse an ERDDAP DDS file for dataset type and dimension ordering."""
    with open(filepath) as f:
        content = f.read()

    result = {'type': None, 'dimensions': []}

    if 'GRID' in content:
        result['type'] = 'grid'
        array_match = re.search(r'ARRAY:\s*\n\s+\w+\s+\w+(.+?);', content)
        if array_match:
            for dim_match in re.finditer(r'\[(\w+)\s*=\s*\d+\]', array_match.group(1)):
                result['dimensions'].append(dim_match.group(1))
    elif 'Sequence' in content:
        result['type'] = 'table'

    return result


def load_datasets(metadata_dir, registry):
    """Load dataset metadata from DAS/DDS files combined with registry."""
    datasets = {}

    for das_path in sorted(Path(metadata_dir).glob('*.das')):
        ds_id = das_path.stem
        dds_path = das_path.with_suffix('.dds')

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
                elif dim_name == 'altitude':
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

        datasets[ds_id] = ds

    return datasets


def convert_lon(lon, from_conv, to_conv):
    """Convert a longitude value between coordinate conventions."""
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


def process_griddap(ds, query, request):
    """Generate query plan for a griddap (gridded) dataset."""
    query_lon_conv = query['region']['lonConvention']
    ds_lon_conv = ds['lonConvention']
    lat_range = query['region']['latitude']
    lon_range = query['region']['longitude']
    time_range = query.get('time')
    target_res = request.get('targetResolution')
    variables = request['variables']

    lon_start = convert_lon(lon_range[0], query_lon_conv, ds_lon_conv)
    lon_stop = convert_lon(lon_range[1], query_lon_conv, ds_lon_conv)
    antimeridian_split = (lon_start > lon_stop)

    lon_dim = get_dim(ds, 'longitude')
    lat_dim = get_dim(ds, 'latitude')
    alt_dim = get_dim(ds, 'altitude')

    lat_stride = compute_stride(target_res, lat_dim['spacing'])
    lon_stride = compute_stride(target_res, lon_dim['spacing'])

    if antimeridian_split:
        lon_ranges = [
            {'start': lon_dim['start'], 'stop': lon_stop, 'stride': lon_stride},
            {'start': lon_start, 'stop': lon_dim['stop'], 'stride': lon_stride},
        ]
    else:
        lon_ranges = [
            {'start': lon_start, 'stop': lon_stop, 'stride': lon_stride}
        ]

    urls = []
    dim_order = ds['dds']['dimensions']

    for lr in lon_ranges:
        dim_constraints = []
        for dim_name in dim_order:
            if dim_name == 'time' and time_range:
                dim_constraints.append(
                    build_griddap_dim_constraint(time_range['start'], time_range['stop'], 1))
            elif dim_name == 'altitude' and alt_dim:
                dim_constraints.append(
                    build_griddap_dim_constraint(None, None, 1, single_value=alt_dim['values'][0]))
            elif dim_name == 'latitude':
                dim_constraints.append(
                    build_griddap_dim_constraint(lat_range[0], lat_range[1], lat_stride))
            elif dim_name == 'longitude':
                dim_constraints.append(
                    build_griddap_dim_constraint(lr['start'], lr['stop'], lr['stride']))

        urls.append(build_griddap_url(ds['baseUrl'], ds['datasetID'], variables, dim_constraints))

    result = {
        'dataset_id': ds['datasetID'],
        'query_type': 'griddap',
        'variables': variables,
        'urls': urls,
        'antimeridian_split': antimeridian_split,
        'constraints': {
            'latitude': {'start': lat_range[0], 'stop': lat_range[1], 'stride': lat_stride},
            'longitude': lon_ranges,
        },
    }

    if time_range:
        result['constraints']['time'] = {
            'start': time_range['start'],
            'stop': time_range['stop'],
            'stride': 1,
        }

    if alt_dim:
        result['constraints']['altitude'] = {'value': alt_dim['values'][0]}

    return result


def process_tabledap(ds, query, request):
    """Generate query plan for a tabledap (tabular) dataset."""
    query_lon_conv = query['region']['lonConvention']
    ds_lon_conv = ds['lonConvention']
    lat_range = query['region']['latitude']
    lon_range = query['region']['longitude']
    time_range = query.get('time')
    variables = request['variables']

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
        urls.append(build_tabledap_url(ds['baseUrl'], ds['datasetID'], variables, filters))

    result = {
        'dataset_id': ds['datasetID'],
        'query_type': 'tabledap',
        'variables': variables,
        'urls': urls,
        'antimeridian_split': antimeridian_split,
        'constraints': {
            'latitude': {'start': lat_range[0], 'stop': lat_range[1]},
            'longitude': lon_ranges,
        },
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

    with open('/app/queries.json') as f:
        queries = json.load(f)

    output = {}
    for query in queries:
        qid = query['id']
        subqueries = []
        for req in query['requests']:
            ds = datasets[req['datasetID']]
            if ds['type'] == 'grid':
                subqueries.append(process_griddap(ds, query, req))
            elif ds['type'] == 'table':
                subqueries.append(process_tabledap(ds, query, req))
        output[qid] = subqueries

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/query_plan.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('Query plan written to /app/output/query_plan.json')


if __name__ == '__main__':
    main()
