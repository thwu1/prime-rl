#!/bin/bash
#
# Validation pipeline for cfs-tool
# Exercises the full layer store workflow against test data.

TOOL="/app/cfs-tool"
LAYERS="/app/layers"
WORK="/tmp/pipeline_$$"
rm -rf "$WORK"
mkdir -p "$WORK/store" "$WORK/manifests" "$WORK/checkout"

PASS=0
FAIL=0

check() {
    local num="$1" desc="$2"
    shift 2
    if "$@"; then
        echo "CHECK $num PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "CHECK $num FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

# ── Import all layers ──────────────────────────────────────────────────────
"$TOOL" import "$LAYERS/base" "$WORK/store" --manifest "$WORK/manifests/base.json"
"$TOOL" import "$LAYERS/app" "$WORK/store" --manifest "$WORK/manifests/app.json"
"$TOOL" import "$LAYERS/patch" "$WORK/store" --manifest "$WORK/manifests/patch.json"

# CHECK 1: Manifest mode values are 4-digit zero-padded octal
check 1 "mode values are 4-digit octal" python3 -c "
import json, sys
data = json.load(open('$WORK/manifests/base.json'))
for e in data['entries']:
    if 'mode' in e:
        m = e['mode']
        if len(m) != 4 or not all(c in '01234567' for c in m):
            print(f\"  mode '{m}' for {e['path']} is not 4-digit octal\", file=sys.stderr)
            sys.exit(1)
"

# CHECK 2: Symlinks recorded with correct type and target
check 2 "symlinks recorded as type=symlink with link_target" python3 -c "
import json, sys
data = json.load(open('$WORK/manifests/base.json'))
entries = {e['path']: e for e in data['entries']}
e = entries.get('usr/lib/libfoo.so')
if not e:
    print('  usr/lib/libfoo.so missing from manifest', file=sys.stderr); sys.exit(1)
if e['type'] != 'symlink':
    print(f\"  type={e['type']}, expected symlink\", file=sys.stderr); sys.exit(1)
if e.get('link_target') != 'libfoo.so.1':
    print(f\"  link_target={e.get('link_target')}, expected libfoo.so.1\", file=sys.stderr); sys.exit(1)
"

# CHECK 3: Content deduplication across layers
check 3 "shared content is deduplicated across layers" python3 -c "
import json, sys
base = json.load(open('$WORK/manifests/base.json'))
app = json.load(open('$WORK/manifests/app.json'))
be = {e['path']: e for e in base['entries']}
ae = {e['path']: e for e in app['entries']}
b_hash = be.get('usr/lib/libfoo.so.1', {}).get('sha256', '')
a_hash = ae.get('usr/lib/libfoo.so.1', {}).get('sha256', '')
if b_hash != a_hash or not b_hash:
    print(f'  base sha256={b_hash} app sha256={a_hash}', file=sys.stderr); sys.exit(1)
"

# ── Merge layers ───────────────────────────────────────────────────────────
"$TOOL" merge "$WORK/manifests/base.json" "$WORK/manifests/app.json" \
    --output "$WORK/manifests/merged1.json"
"$TOOL" merge "$WORK/manifests/merged1.json" "$WORK/manifests/patch.json" \
    --output "$WORK/manifests/merged_final.json"

# CHECK 4: Opaque whiteout scoped correctly — etc_backup not affected
check 4 "opaque whiteout does not affect etc_backup directory" python3 -c "
import json, sys
data = json.load(open('$WORK/manifests/merged_final.json'))
paths = {e['path'] for e in data['entries']}
if 'etc_backup' not in paths:
    print('  etc_backup directory missing from merged result', file=sys.stderr); sys.exit(1)
if 'etc_backup/config.ini.bak' not in paths:
    print('  etc_backup/config.ini.bak missing from merged result', file=sys.stderr); sys.exit(1)
"

# CHECK 5: Overlay entries at whiteout paths survive merge
check 5 "overlay entry at whiteout path preserved in merge" python3 -c "
import json, sys
merged = json.load(open('$WORK/manifests/merged_final.json'))
patch = json.load(open('$WORK/manifests/patch.json'))
me = {e['path']: e for e in merged['entries']}
pe = {e['path']: e for e in patch['entries']}
if 'usr/lib/libapp.so.1' not in me:
    print('  usr/lib/libapp.so.1 missing — overlay entry deleted by its own whiteout', file=sys.stderr)
    sys.exit(1)
if me['usr/lib/libapp.so.1'].get('sha256') != pe['usr/lib/libapp.so.1'].get('sha256'):
    print('  wrong version of libapp.so.1 — not the overlay version', file=sys.stderr); sys.exit(1)
"

# CHECK 6: Old etc/ entries correctly removed by opaque whiteout
check 6 "opaque whiteout removes old etc entries" python3 -c "
import json, sys
data = json.load(open('$WORK/manifests/merged_final.json'))
paths = {e['path'] for e in data['entries']}
for p in ['etc/config.ini', 'etc/hosts', 'etc/app.conf']:
    if p in paths:
        print(f'  {p} should have been removed by opaque whiteout', file=sys.stderr)
        sys.exit(1)
if 'etc/minimal.conf' not in paths:
    print('  etc/minimal.conf from overlay should survive', file=sys.stderr); sys.exit(1)
"

# CHECK 7: Diff detects modified entries
check 7 "diff detects content modifications between manifests" python3 -c "
import json, subprocess, sys
r = subprocess.run(['$TOOL', 'diff', '$WORK/manifests/base.json', '$WORK/manifests/app.json'],
    capture_output=True, text=True)
if r.returncode != 0:
    print(f'  diff command failed: {r.stderr}', file=sys.stderr); sys.exit(1)
d = json.loads(r.stdout)
if 'usr/bin/hello' not in d.get('modified', []):
    print(f\"  'modified' list = {d.get('modified', [])} — expected usr/bin/hello\", file=sys.stderr)
    sys.exit(1)
"

# CHECK 8: gc removes unreferenced objects
cp -r "$WORK/manifests" "$WORK/gc_manifests"
rm -f "$WORK/gc_manifests/app.json" "$WORK/gc_manifests/merged1.json" "$WORK/gc_manifests/patch.json"
cp -r "$WORK/store" "$WORK/gc_store"

check 8 "gc removes unreferenced objects from store" python3 -c "
import json, subprocess, sys
r = subprocess.run(['$TOOL', 'gc', '$WORK/gc_store', '$WORK/gc_manifests'],
    capture_output=True, text=True)
if r.returncode != 0:
    print(f'  gc exited {r.returncode}: {r.stderr}', file=sys.stderr); sys.exit(1)
try:
    gc = json.loads(r.stdout)
except json.JSONDecodeError:
    print(f'  gc output is not valid JSON: {r.stdout[:200]}', file=sys.stderr); sys.exit(1)
if gc.get('removed_objects', 0) == 0:
    print('  expected some objects to be removed', file=sys.stderr); sys.exit(1)
if gc.get('remaining_objects', 0) == 0:
    print('  expected some objects to remain', file=sys.stderr); sys.exit(1)
"

# CHECK 9: Referenced objects still valid after gc
check 9 "verify passes on remaining manifests after gc" bash -c "
'$TOOL' verify '$WORK/gc_manifests/base.json' '$WORK/gc_store' | grep -q OK && \
'$TOOL' verify '$WORK/gc_manifests/merged_final.json' '$WORK/gc_store' | grep -q OK
"

# CHECK 10: Checkout produces correct filesystem tree
"$TOOL" checkout "$WORK/manifests/merged_final.json" "$WORK/store" "$WORK/checkout"

check 10 "checkout produces correct filesystem content and structure" python3 -c "
import os, sys
co = '$WORK/checkout'
errors = []
# Patched app binary
with open(os.path.join(co, 'usr/bin/app')) as f:
    if 'App v2 patched' not in f.read():
        errors.append('wrong app content — expected App v2 patched')
# Base tool preserved
with open(os.path.join(co, 'usr/bin/tool')) as f:
    if 'Tool v1' not in f.read():
        errors.append('wrong tool content — expected Tool v1')
# Symlink preserved
link = os.path.join(co, 'usr/lib/libfoo.so')
if not os.path.islink(link):
    errors.append('libfoo.so is not a symlink')
elif os.readlink(link) != 'libfoo.so.1':
    errors.append(f'symlink target is {os.readlink(link)}, expected libfoo.so.1')
# etc_backup preserved
if not os.path.exists(os.path.join(co, 'etc_backup/config.ini.bak')):
    errors.append('etc_backup/config.ini.bak missing from checkout')
# etc has only minimal.conf
etc_dir = os.path.join(co, 'etc')
if os.path.isdir(etc_dir):
    etc_files = sorted(f for f in os.listdir(etc_dir)
                       if os.path.isfile(os.path.join(etc_dir, f)))
    if etc_files != ['minimal.conf']:
        errors.append(f'etc/ contains {etc_files}, expected only [minimal.conf]')
else:
    errors.append('etc/ directory missing from checkout')
if errors:
    for e in errors:
        print(f'  {e}', file=sys.stderr)
    sys.exit(1)
"

# CHECK 11: fsck reports clean on valid store
check 11 "fsck reports clean on valid store" python3 -c "
import json, subprocess, sys
r = subprocess.run(['$TOOL', 'fsck', '$WORK/store', '$WORK/manifests'],
    capture_output=True, text=True)
if r.returncode != 0:
    print(f'  fsck exited {r.returncode}: {r.stderr}', file=sys.stderr); sys.exit(1)
try:
    d = json.loads(r.stdout)
except json.JSONDecodeError:
    print(f'  fsck output is not valid JSON: {r.stdout[:200]}', file=sys.stderr); sys.exit(1)
if d.get('status') != 'clean':
    print(f'  expected clean, got {d.get(\"status\")}: {d.get(\"errors\", [])}', file=sys.stderr)
    sys.exit(1)
for key in ['manifests_checked', 'objects_checked', 'orphaned_objects', 'errors']:
    if key not in d:
        print(f'  missing key in fsck output: {key}', file=sys.stderr); sys.exit(1)
"

# CHECK 12: store-audit.sh produces valid report
check 12 "store-audit.sh produces valid health report" python3 -c "
import json, subprocess, sys
r = subprocess.run(['/app/store-audit.sh', '$WORK/store', '$WORK/manifests'],
    capture_output=True, text=True)
if r.returncode != 0:
    print(f'  store-audit.sh exited {r.returncode}: {r.stderr}', file=sys.stderr); sys.exit(1)
try:
    d = json.loads(r.stdout)
except json.JSONDecodeError:
    print(f'  store-audit.sh output is not valid JSON: {r.stdout[:200]}', file=sys.stderr); sys.exit(1)
for key in ['total_objects', 'referenced_objects', 'orphaned_objects', 'integrity_errors', 'status']:
    if key not in d:
        print(f'  missing key: {key}', file=sys.stderr); sys.exit(1)
if d.get('status') != 'ok':
    print(f'  expected ok, got {d.get(\"status\")}', file=sys.stderr); sys.exit(1)
"

echo ""
echo "════════════════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed out of $((PASS + FAIL)) checks"
echo "════════════════════════════════════════════════════"
[ $FAIL -eq 0 ] && exit 0 || exit 1
