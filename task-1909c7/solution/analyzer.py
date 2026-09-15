#!/usr/bin/env python3
"""Kernel SLUB Cache Collision Analyzer — processes raw kernel artifacts."""


import json
import os
import re
import sqlite3
import sys


def parse_kasan_report(filepath):
    """Parse a KASAN report file to extract vulnerability parameters."""
    with open(filepath) as f:
        text = f.read()

    if 'use-after-free' in text:
        vuln_type = 'uaf_write'
    elif 'slab-out-of-bounds' in text:
        vuln_type = 'oob_write'
    else:
        raise ValueError(f"Unknown KASAN bug type in {filepath}")

    m = re.search(r'Write of size (\d+) at addr', text)
    write_size = int(m.group(1))

    m = re.search(r'belongs to the cache (\S+) of size (\d+)', text)
    cache_name = m.group(1)
    obj_size = int(m.group(2))

    m = re.search(r'located (\d+) bytes inside of', text)
    offset = int(m.group(1))

    vuln_id = os.path.splitext(os.path.basename(filepath))[0]

    return {
        'id': vuln_id,
        'type': vuln_type,
        'source_cache': cache_name,
        'source_object_size': obj_size,
        'controllable_offset': offset,
        'controllable_bytes': write_size,
    }


def load_sysfs_caches(sysfs_dir):
    """Read cache attributes from sysfs-like directory structure."""
    caches = {}
    for cache_name in sorted(os.listdir(sysfs_dir)):
        cache_path = os.path.join(sysfs_dir, cache_name)
        if not os.path.isdir(cache_path):
            continue
        attrs = {}
        for attr_file in os.listdir(cache_path):
            attr_path = os.path.join(cache_path, attr_file)
            if os.path.isfile(attr_path):
                with open(attr_path) as f:
                    attrs[attr_file] = f.read().strip()
        caches[cache_name] = attrs
    return caches


def load_structures_from_db(db_path):
    """Query kernel structure data from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    structures = []
    for row in conn.execute('SELECT * FROM structures ORDER BY name'):
        struct = {
            'name': row['name'],
            'size': row['size'],
            'cache': row['alloc_cache'],
            'fields': []
        }

        for field_row in conn.execute(
            'SELECT * FROM fields WHERE struct_name = ? ORDER BY byte_offset',
            (row['name'],)
        ):
            caps = conn.execute(
                'SELECT capability, exploit_method FROM security_properties '
                'WHERE struct_name = ? AND field_name = ?',
                (row['name'], field_row['field_name'])
            ).fetchall()

            field = {
                'name': field_row['field_name'],
                'offset': field_row['byte_offset'],
                'size': field_row['byte_size'],
                'security_relevant': len(caps) > 0,
                'capabilities': [c['capability'] for c in caps],
                'exploit_method': caps[0]['exploit_method'] if caps else None,
            }
            struct['fields'].append(field)

        structures.append(struct)

    conn.close()
    return structures


def determine_kmalloc_caches(sysfs_caches):
    """Identify kmalloc caches from sysfs data."""
    kmalloc = []
    for name, attrs in sysfs_caches.items():
        if name.startswith('kmalloc-'):
            kmalloc.append({
                'name': name,
                'object_size': int(attrs['object_size']),
                'align': int(attrs['align']),
            })
    return sorted(kmalloc, key=lambda c: c['object_size'])


def is_cache_unmergeable(attrs):
    """Check if a named cache cannot be merged based on sysfs attributes."""
    if attrs.get('ctor', ''):
        return True
    if attrs.get('destroy_by_rcu', '0') == '1':
        return True
    if attrs.get('poison', '0') == '1':
        return True
    if attrs.get('store_user', '0') == '1':
        return True
    if attrs.get('trace', '0') == '1':
        return True
    return False


def find_kmalloc_class(size, kmalloc_caches):
    """Find smallest kmalloc cache with object_size >= size."""
    for cache in kmalloc_caches:
        if cache['object_size'] >= size:
            return cache['name']
    return None


def compute_cache_merging(sysfs_caches):
    """Determine which named caches merge into kmalloc caches."""
    kmalloc = determine_kmalloc_caches(sysfs_caches)

    merged = {}
    standalone = []

    for name, attrs in sorted(sysfs_caches.items()):
        if name.startswith('kmalloc-'):
            continue
        if is_cache_unmergeable(attrs):
            standalone.append(name)
        else:
            obj_size = int(attrs['object_size'])
            target = find_kmalloc_class(obj_size, kmalloc)
            if target:
                cache_align = int(attrs.get('align', '8'))
                target_attrs = sysfs_caches.get(target, {})
                target_align = int(target_attrs.get('align', '8'))
                if target_align >= cache_align:
                    merged[name] = target
                else:
                    standalone.append(name)
            else:
                standalone.append(name)

    return merged, standalone


def get_effective_cache(cache_name, merged_caches, kmalloc_names):
    """Resolve cache name to effective physical cache."""
    if cache_name in kmalloc_names:
        return cache_name
    if cache_name in merged_caches:
        return merged_caches[cache_name]
    return cache_name


def compute_controllable_region(vuln):
    """Compute controllable byte region in the target object."""
    if vuln['type'] == 'uaf_write':
        return vuln['controllable_offset'], vuln['controllable_bytes']
    elif vuln['type'] == 'oob_write':
        write_end = vuln['controllable_offset'] + vuln['controllable_bytes']
        overflow = write_end - vuln['source_object_size']
        if overflow <= 0:
            return None, 0
        return 0, overflow
    return vuln['controllable_offset'], vuln['controllable_bytes']


def field_overlaps_region(field, ctrl_offset, ctrl_size):
    """Check if a structure field overlaps with the controllable region."""
    ctrl_end = ctrl_offset + ctrl_size
    field_start = field['offset']
    field_end = field_start + field['size']
    return max(ctrl_offset, field_start) < min(ctrl_end, field_end)


def check_mitigation(capability, method, mitigations):
    """Check if a capability+method pair is blocked by active mitigations."""
    active = mitigations['active_mitigations']
    effects = mitigations['mitigation_effects']

    for effect in effects:
        mit_name = effect['mitigation']
        if not active.get(mit_name, False):
            continue
        blocks = effect['blocks']
        if blocks.get('capability') == '*':
            return True, mit_name
        if blocks.get('capability') == capability and blocks.get('method') == method:
            return True, mit_name

    return False, None


def analyze_vulnerability(vuln, structures, merged_caches, kmalloc_names, mitigations):
    """Analyze a single vulnerability for exploit feasibility."""
    effective_cache = get_effective_cache(
        vuln['source_cache'], merged_caches, kmalloc_names
    )

    ctrl_offset, ctrl_size = compute_controllable_region(vuln)

    result = {
        'vuln_id': vuln['id'],
        'vuln_type': vuln['type'],
        'source_cache': vuln['source_cache'],
        'effective_cache': effective_cache,
        'reachable_targets': [],
    }

    if ctrl_size is None or ctrl_size <= 0:
        return result

    collision_type = 'adjacent_object' if vuln['type'] == 'oob_write' else 'same_cache'

    for struct in structures:
        struct_effective = get_effective_cache(
            struct['cache'], merged_caches, kmalloc_names
        )
        if struct_effective != effective_cache:
            continue

        controllable_fields = []
        for field in struct['fields']:
            if not field['security_relevant']:
                continue
            if not field_overlaps_region(field, ctrl_offset, ctrl_size):
                continue

            for cap in field['capabilities']:
                method = field['exploit_method'] or 'unknown'
                mitigated, reason = check_mitigation(cap, method, mitigations)
                controllable_fields.append({
                    'field_name': field['name'],
                    'field_offset': field['offset'],
                    'field_size': field['size'],
                    'capability': cap,
                    'exploit_method': method,
                    'mitigated': mitigated,
                    'mitigation_reason': reason,
                })

        if controllable_fields:
            result['reachable_targets'].append({
                'structure': struct['name'],
                'target_cache': struct['cache'],
                'collision_type': collision_type,
                'controllable_region': {
                    'offset_in_target': ctrl_offset,
                    'size': ctrl_size,
                },
                'controllable_fields': controllable_fields,
            })

    return result


def main():
    base_dir = '/app'

    mitigations_path = os.path.join(base_dir, 'mitigations.json')
    if '--mitigations' in sys.argv:
        idx = sys.argv.index('--mitigations')
        if idx + 1 < len(sys.argv):
            mitigations_path = sys.argv[idx + 1]

    sysfs_caches = load_sysfs_caches(os.path.join(base_dir, 'sysfs_slab'))
    structures = load_structures_from_db(os.path.join(base_dir, 'kernel_structs.db'))
    with open(mitigations_path) as f:
        mitigations = json.load(f)

    kasan_dir = os.path.join(base_dir, 'kasan_reports')
    vulns = []
    for fname in sorted(os.listdir(kasan_dir)):
        if fname.endswith('.txt'):
            vulns.append(parse_kasan_report(os.path.join(kasan_dir, fname)))

    merged_caches, standalone_caches = compute_cache_merging(sysfs_caches)
    kmalloc_names = {name for name in sysfs_caches if name.startswith('kmalloc-')}

    vuln_analyses = []
    for vuln in vulns:
        analysis = analyze_vulnerability(
            vuln, structures, merged_caches, kmalloc_names, mitigations
        )
        vuln_analyses.append(analysis)

    output = {
        'cache_analysis': {
            'merged_caches': merged_caches,
            'standalone_caches': standalone_caches,
        },
        'vulnerability_analysis': vuln_analyses,
    }

    os.makedirs(os.path.join(base_dir, 'output'), exist_ok=True)
    output_path = os.path.join(base_dir, 'output', 'analysis.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'Analysis written to {output_path}')


if __name__ == '__main__':
    main()
