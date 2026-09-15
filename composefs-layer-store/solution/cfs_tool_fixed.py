#!/usr/bin/env python3
"""
Content-Addressed Layer Store Tool (cfs-tool) — Fixed Version

Fixes applied:
1. format_mode: zero-padded 4-digit octal
2. import: symlink detection before stat
3. merge: correct opaque prefix matching (path == od or path.startswith(od + '/'))
4. merge: whiteouts applied only to base entries, not overlay
5. diff: attribute-level modification detection
6. gc: garbage collection subcommand
7. fsck: comprehensive integrity checking subcommand
"""

import argparse
import hashlib
import json
import os
import stat
import sys


def sha256_of_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def store_object(store_dir, data):
    """Store data in the content-addressed object store. Returns digest."""
    digest = sha256_of_bytes(data)
    prefix = digest[:2]
    obj_dir = os.path.join(store_dir, 'objects', prefix)
    obj_path = os.path.join(obj_dir, digest)
    if not os.path.exists(obj_path):
        os.makedirs(obj_dir, exist_ok=True)
        with open(obj_path, 'wb') as f:
            f.write(data)
    return digest


def format_mode(st_mode):
    """Format POSIX permission bits as 4-digit zero-padded octal string."""
    return f"{stat.S_IMODE(st_mode):04o}"


# ── import ────────────────────────────────────────────────────────────────


def cmd_import(source_dir, store_dir, manifest_path):
    entries = []
    whiteouts = []
    opaque = []

    # Check for .whiteouts.json sidecar
    wh_path = os.path.join(source_dir, '.whiteouts.json')
    if os.path.exists(wh_path):
        with open(wh_path) as f:
            wh_data = json.load(f)
        whiteouts = sorted(wh_data.get('remove', []))
        opaque = sorted(wh_data.get('opaque', []))

    for root, dirs, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        if rel_root == '.':
            rel_root = ''

        # Add directory entry (skip root directory itself)
        if rel_root:
            dir_stat = os.stat(root)
            entries.append({
                'path': rel_root.replace(os.sep, '/'),
                'type': 'directory',
                'mode': format_mode(dir_stat.st_mode),
            })

        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, source_dir).replace(os.sep, '/')
            if rel_path == '.whiteouts.json':
                continue

            # Check symlink BEFORE stat to avoid following the link
            if os.path.islink(fpath):
                entries.append({
                    'path': rel_path,
                    'type': 'symlink',
                    'link_target': os.readlink(fpath),
                })
            else:
                fstat = os.stat(fpath)
                size = fstat.st_size
                entry = {
                    'path': rel_path,
                    'type': 'file',
                    'size': size,
                    'mode': format_mode(fstat.st_mode),
                }
                if size > 0:
                    with open(fpath, 'rb') as f:
                        data = f.read()
                    entry['sha256'] = store_object(store_dir, data)
                entries.append(entry)

    entries.sort(key=lambda e: e['path'])
    manifest = {
        'version': 1,
        'entries': entries,
        'whiteouts': whiteouts,
        'opaque': opaque,
    }

    os.makedirs(os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True)
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)


# ── checkout ──────────────────────────────────────────────────────────────


def cmd_checkout(manifest_path, store_dir, output_dir):
    with open(manifest_path) as f:
        data = json.load(f)

    os.makedirs(output_dir, exist_ok=True)

    # First pass: create all directories
    for entry in data['entries']:
        if entry['type'] == 'directory':
            path = os.path.join(output_dir, entry['path'])
            os.makedirs(path, exist_ok=True)

    # Second pass: create files and symlinks
    for entry in data['entries']:
        path = os.path.join(output_dir, entry['path'])
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        if entry['type'] == 'file':
            if entry.get('size', 0) > 0:
                digest = entry['sha256']
                obj_path = os.path.join(store_dir, 'objects', digest[:2], digest)
                with open(obj_path, 'rb') as src, open(path, 'wb') as dst:
                    dst.write(src.read())
            else:
                open(path, 'w').close()
            os.chmod(path, int(entry['mode'], 8))

        elif entry['type'] == 'symlink':
            if os.path.lexists(path):
                os.remove(path)
            os.symlink(entry['link_target'], path)

    # Final pass: set directory modes (after all contents created)
    for entry in data['entries']:
        if entry['type'] == 'directory':
            path = os.path.join(output_dir, entry['path'])
            os.chmod(path, int(entry['mode'], 8))


# ── verify ────────────────────────────────────────────────────────────────


def cmd_verify(manifest_path, store_dir):
    with open(manifest_path) as f:
        data = json.load(f)

    failed = False
    for entry in data['entries']:
        if entry['type'] == 'file' and entry.get('size', 0) > 0:
            digest = entry['sha256']
            obj_path = os.path.join(store_dir, 'objects', digest[:2], digest)

            if not os.path.exists(obj_path):
                print(f"FAILED: {entry['path']} object missing")
                failed = True
                continue

            actual = sha256_of_file(obj_path)
            if actual != digest:
                print(f"FAILED: {entry['path']} hash mismatch "
                      f"(expected {digest}, got {actual})")
                failed = True

    if failed:
        sys.exit(1)
    else:
        print("OK")


# ── diff ──────────────────────────────────────────────────────────────────


def entries_differ(a, b):
    """Return True if two manifest entries differ in any meaningful field."""
    if a['type'] != b['type']:
        return True
    if a['type'] == 'file':
        for key in ('sha256', 'mode', 'size'):
            if a.get(key) != b.get(key):
                return True
    elif a['type'] == 'directory':
        if a.get('mode') != b.get('mode'):
            return True
    elif a['type'] == 'symlink':
        if a.get('link_target') != b.get('link_target'):
            return True
    return False


def cmd_diff(old_path, new_path):
    with open(old_path) as f:
        old_data = json.load(f)
    with open(new_path) as f:
        new_data = json.load(f)

    old_entries = {e['path']: e for e in old_data['entries']}
    new_entries = {e['path']: e for e in new_data['entries']}

    old_paths = set(old_entries)
    new_paths = set(new_entries)

    added = sorted(new_paths - old_paths)
    removed = sorted(old_paths - new_paths)
    modified = sorted(
        p for p in old_paths & new_paths
        if entries_differ(old_entries[p], new_entries[p])
    )

    print(json.dumps({
        'added': added,
        'removed': removed,
        'modified': modified,
    }, indent=2))


# ── merge ─────────────────────────────────────────────────────────────────


def cmd_merge(base_path, overlay_path, output_path):
    with open(base_path) as f:
        base_data = json.load(f)
    with open(overlay_path) as f:
        overlay_data = json.load(f)

    base_entries = {e['path']: e for e in base_data['entries']}
    overlay_entries = {e['path']: e for e in overlay_data['entries']}

    opaque_dirs = set(overlay_data.get('opaque', []))
    whiteout_targets = set(overlay_data.get('whiteouts', []))

    merged = {}

    # 1. Start with base entries, filtering out opaque/whiteout removals
    for path, entry in base_entries.items():
        # Correct opaque check: exact match or path under opaque dir
        is_opaque = any(
            path == od or path.startswith(od + '/')
            for od in opaque_dirs
        )
        if is_opaque:
            continue

        if path in whiteout_targets:
            continue

        merged[path] = entry

    # 2. Add overlay entries (whiteouts are NOT re-applied)
    for path, entry in overlay_entries.items():
        merged[path] = entry

    # 3. Sort and write — whiteouts consumed, not propagated
    sorted_entries = sorted(merged.values(), key=lambda e: e['path'])
    manifest = {
        'version': 1,
        'entries': sorted_entries,
        'whiteouts': [],
        'opaque': [],
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(manifest, f, indent=2)


# ── stats ─────────────────────────────────────────────────────────────────


def cmd_stats(store_dir):
    objects_dir = os.path.join(store_dir, 'objects')
    total_objects = 0
    total_size = 0

    if os.path.exists(objects_dir):
        for prefix_dir in os.listdir(objects_dir):
            prefix_path = os.path.join(objects_dir, prefix_dir)
            if os.path.isdir(prefix_path):
                for obj_name in os.listdir(prefix_path):
                    obj_path = os.path.join(prefix_path, obj_name)
                    if os.path.isfile(obj_path):
                        total_objects += 1
                        total_size += os.path.getsize(obj_path)

    print(json.dumps({
        'total_objects': total_objects,
        'total_size_bytes': total_size,
    }, indent=2))


# ── gc ────────────────────────────────────────────────────────────────────


def cmd_gc(store_dir, manifests_dir):
    """Remove objects not referenced by any manifest in manifests_dir."""
    referenced = set()

    for fname in os.listdir(manifests_dir):
        if not fname.endswith('.json'):
            continue
        manifest_path = os.path.join(manifests_dir, fname)
        try:
            with open(manifest_path) as f:
                data = json.load(f)
            for entry in data.get('entries', []):
                if entry.get('type') == 'file' and 'sha256' in entry:
                    referenced.add(entry['sha256'])
        except (json.JSONDecodeError, KeyError):
            continue

    objects_dir = os.path.join(store_dir, 'objects')
    removed = 0
    freed = 0
    remaining = 0

    if os.path.exists(objects_dir):
        for prefix_dir in os.listdir(objects_dir):
            prefix_path = os.path.join(objects_dir, prefix_dir)
            if not os.path.isdir(prefix_path):
                continue
            for obj_name in list(os.listdir(prefix_path)):
                obj_path = os.path.join(prefix_path, obj_name)
                if not os.path.isfile(obj_path):
                    continue
                if obj_name not in referenced:
                    size = os.path.getsize(obj_path)
                    os.remove(obj_path)
                    removed += 1
                    freed += size
                else:
                    remaining += 1
            # Clean up empty prefix directories
            if not os.listdir(prefix_path):
                os.rmdir(prefix_path)

    print(json.dumps({
        'removed_objects': removed,
        'freed_bytes': freed,
        'remaining_objects': remaining,
    }, indent=2))


# ── fsck ──────────────────────────────────────────────────────────────────


def cmd_fsck(store_dir, manifests_dir):
    """Comprehensive integrity check of store and manifests."""
    errors = []
    manifests_checked = 0
    objects_checked = set()
    all_referenced = set()

    for fname in sorted(os.listdir(manifests_dir)):
        if not fname.endswith('.json'):
            continue
        manifest_path = os.path.join(manifests_dir, fname)
        manifests_checked += 1

        try:
            with open(manifest_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            errors.append({
                'manifest': fname,
                'type': 'schema_violation',
                'detail': f'Cannot parse manifest: {e}',
            })
            continue

        # Schema checks
        if data.get('version') != 1:
            errors.append({
                'manifest': fname,
                'type': 'schema_violation',
                'detail': f"Invalid version: {data.get('version')}",
            })

        if not isinstance(data.get('entries'), list):
            errors.append({
                'manifest': fname,
                'type': 'schema_violation',
                'detail': "Missing or invalid 'entries' field",
            })
            continue

        if not isinstance(data.get('whiteouts'), list):
            errors.append({
                'manifest': fname,
                'type': 'schema_violation',
                'detail': "Missing or invalid 'whiteouts' field",
            })

        if not isinstance(data.get('opaque'), list):
            errors.append({
                'manifest': fname,
                'type': 'schema_violation',
                'detail': "Missing or invalid 'opaque' field",
            })

        # Sort order check
        paths = [e.get('path', '') for e in data['entries']]
        if paths != sorted(paths):
            errors.append({
                'manifest': fname,
                'type': 'sort_violation',
                'detail': 'Entries not sorted by path',
            })

        # Duplicate path check
        seen_paths = set()
        for p in paths:
            if p in seen_paths:
                errors.append({
                    'manifest': fname,
                    'type': 'duplicate_path',
                    'detail': f'Duplicate path: {p}',
                })
            seen_paths.add(p)

        # Entry validation + object checks
        for entry in data['entries']:
            if 'path' not in entry or 'type' not in entry:
                errors.append({
                    'manifest': fname,
                    'type': 'schema_violation',
                    'detail': 'Entry missing path or type',
                })
                continue

            etype = entry['type']

            if etype == 'file':
                size = entry.get('size', 0)
                if size > 0:
                    if 'sha256' not in entry:
                        errors.append({
                            'manifest': fname,
                            'type': 'schema_violation',
                            'detail': f"File {entry['path']} has size>0 but no sha256",
                        })
                        continue

                    digest = entry['sha256']
                    all_referenced.add(digest)
                    obj_path = os.path.join(
                        store_dir, 'objects', digest[:2], digest)

                    if not os.path.exists(obj_path):
                        errors.append({
                            'manifest': fname,
                            'type': 'missing_object',
                            'detail': f"Object {digest[:16]}... missing for {entry['path']}",
                        })
                    elif digest not in objects_checked:
                        objects_checked.add(digest)
                        actual = sha256_of_file(obj_path)
                        if actual != digest:
                            errors.append({
                                'manifest': fname,
                                'type': 'hash_mismatch',
                                'detail': (f"Object {digest[:16]}... has actual hash "
                                           f"{actual[:16]}... for {entry['path']}"),
                            })

    # Orphan detection
    all_objects = set()
    objects_dir = os.path.join(store_dir, 'objects')
    if os.path.exists(objects_dir):
        for prefix_dir in os.listdir(objects_dir):
            prefix_path = os.path.join(objects_dir, prefix_dir)
            if os.path.isdir(prefix_path):
                for obj_name in os.listdir(prefix_path):
                    if os.path.isfile(os.path.join(prefix_path, obj_name)):
                        all_objects.add(obj_name)

    orphaned = len(all_objects - all_referenced)

    # Status based on errors only (orphans are informational)
    status = 'clean' if not errors else 'dirty'

    result = {
        'status': status,
        'manifests_checked': manifests_checked,
        'objects_checked': len(objects_checked),
        'orphaned_objects': orphaned,
        'errors': errors,
    }

    print(json.dumps(result, indent=2))

    if status == 'dirty':
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description='Content-Addressed Layer Store Tool')
    sub = parser.add_subparsers(dest='command')

    p = sub.add_parser('import')
    p.add_argument('source_dir')
    p.add_argument('store_dir')
    p.add_argument('--manifest', required=True)

    p = sub.add_parser('checkout')
    p.add_argument('manifest')
    p.add_argument('store_dir')
    p.add_argument('output_dir')

    p = sub.add_parser('verify')
    p.add_argument('manifest')
    p.add_argument('store_dir')

    p = sub.add_parser('diff')
    p.add_argument('old_manifest')
    p.add_argument('new_manifest')

    p = sub.add_parser('merge')
    p.add_argument('base_manifest')
    p.add_argument('overlay_manifest')
    p.add_argument('--output', required=True)

    p = sub.add_parser('stats')
    p.add_argument('store_dir')

    p = sub.add_parser('gc')
    p.add_argument('store_dir')
    p.add_argument('manifests_dir')

    p = sub.add_parser('fsck')
    p.add_argument('store_dir')
    p.add_argument('manifests_dir')

    args = parser.parse_args()

    if args.command == 'import':
        cmd_import(args.source_dir, args.store_dir, args.manifest)
    elif args.command == 'checkout':
        cmd_checkout(args.manifest, args.store_dir, args.output_dir)
    elif args.command == 'verify':
        cmd_verify(args.manifest, args.store_dir)
    elif args.command == 'diff':
        cmd_diff(args.old_manifest, args.new_manifest)
    elif args.command == 'merge':
        cmd_merge(args.base_manifest, args.overlay_manifest, args.output)
    elif args.command == 'stats':
        cmd_stats(args.store_dir)
    elif args.command == 'gc':
        cmd_gc(args.store_dir, args.manifests_dir)
    elif args.command == 'fsck':
        cmd_fsck(args.store_dir, args.manifests_dir)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
