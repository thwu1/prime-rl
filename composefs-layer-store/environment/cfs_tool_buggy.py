#!/usr/bin/env python3
"""Content-Addressed Layer Store Tool (cfs-tool)"""

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
    """Format POSIX permission bits as octal string."""
    return f"{stat.S_IMODE(st_mode):o}"


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

            # Process as regular file
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
    modified = []

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

    # Start with base entries, applying opaque removal
    for path, entry in base_entries.items():
        is_opaque = any(path.startswith(od) for od in opaque_dirs)
        if is_opaque:
            continue
        if path in whiteout_targets:
            continue
        merged[path] = entry

    # Add overlay entries
    for path, entry in overlay_entries.items():
        merged[path] = entry

    # Apply whiteout removals
    for wh in whiteout_targets:
        if wh in merged:
            del merged[wh]

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
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
