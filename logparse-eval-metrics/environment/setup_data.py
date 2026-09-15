#!/usr/bin/env python3
"""Generate synthetic log parsing evaluation datasets for benchmark."""

import csv
import os

def write_csv(filepath, rows, fieldnames):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            cleaned = {}
            for k in fieldnames:
                v = row.get(k)
                cleaned[k] = '' if v is None else v
            writer.writerow(cleaned)

FIELDS = ['LineId', 'Content', 'EventId', 'EventTemplate']

# ============================================================
# System A: 100 lines, 5 templates
# Tests: over-generalization, under-generalization, wrong text
# ============================================================
TEMPLATES_A = {
    'E1': ('User admin logged in from 10.0.0.1', 'User <*> logged in from <*>'),
    'E2': ('Connection timeout for server-42', 'Connection timeout for <*>'),
    'E3': ('File config.yaml not found', 'File <*> not found'),
    'E4': ('Process worker-3 started on node-5', 'Process <*> started on <*>'),
    'E5': ('Memory usage at 75 percent', 'Memory usage at <*> percent'),
}
DIST_A = [('E1', 30), ('E2', 25), ('E3', 20), ('E4', 15), ('E5', 10)]

gt_a = []
lid = 1
for eid, count in DIST_A:
    for _ in range(count):
        content, template = TEMPLATES_A[eid]
        gt_a.append({'LineId': lid, 'Content': content,
                     'EventId': eid, 'EventTemplate': template})
        lid += 1

# Parser output perturbation for System A:
#   E1 -> keep correct
#   E2 -> over-generalize: use E1's template text
#   E3 -> keep correct
#   E4 -> under-generalize: split into two different templates
#   E5 -> wrong template text (unique group preserved)
parsed_a = []
e4_idx = 0
for row in gt_a:
    r = dict(row)
    if row['EventId'] == 'E2':
        r['EventTemplate'] = 'User <*> logged in from <*>'
    elif row['EventId'] == 'E4':
        r['EventTemplate'] = 'Process <*> started' if e4_idx < 10 else 'Process started on <*>'
        e4_idx += 1
    elif row['EventId'] == 'E5':
        r['EventTemplate'] = 'Memory at <*> percent'
    parsed_a.append(r)

# ============================================================
# System B: 80 lines, 4 templates
# Tests: over-generalization (merge two groups)
# ============================================================
TEMPLATES_B = {
    'E1': ('BLOCK added to blk_8837493720', 'BLOCK added to <*>'),
    'E2': ('PacketResponder 2 terminating', 'PacketResponder <*> terminating'),
    'E3': ('Received block blk_456912 from 10.0.0.2', 'Received block <*> from <*>'),
    'E4': ('Verification succeeded for blk_789044', 'Verification succeeded for <*>'),
}
DIST_B = [('E1', 30), ('E2', 20), ('E3', 20), ('E4', 10)]

gt_b = []
lid = 1
for eid, count in DIST_B:
    for _ in range(count):
        content, template = TEMPLATES_B[eid]
        gt_b.append({'LineId': lid, 'Content': content,
                     'EventId': eid, 'EventTemplate': template})
        lid += 1

# Parser output: E2 lines get E3's template (over-generalization merge)
parsed_b = []
for row in gt_b:
    r = dict(row)
    if row['EventId'] == 'E2':
        r['EventTemplate'] = 'Received block <*> from <*>'
    parsed_b.append(r)

# ============================================================
# System C: 60 lines, 5 non-null + 5 null templates
# Tests: null handling, special chars, grouping-vs-text accuracy
# ============================================================
TEMPLATES_C = {
    'E1': ('BLOCK* NameSystem.addStoredBlock: blockMap updated: 10.0.0.1:50010 is added to blk_123 size 67108864',
           'BLOCK* NameSystem.addStoredBlock: blockMap updated: <*>:<*> is added to <*> size <*>'),
    'E2': ('Received block blk_456 of size 67108864 from /10.0.0.2',
           'Received block <*> of size <*> from <*>'),
    'E3': ('Error (code=42): segfault in module',
           'Error (code=<*>): <*>'),
    'E4': ('alert [level=WARN] {msg=disk full}',
           'alert [level=<*>] {msg=<*>}'),
    'E5': ('Verification succeeded for blk_789',
           'Verification succeeded for <*>'),
}
DIST_C = [('E1', 15), ('E2', 15), ('E3', 10), ('E4', 10), (None, 5), ('E5', 5)]

gt_c = []
lid = 1
for eid, count in DIST_C:
    for _ in range(count):
        if eid is None:
            gt_c.append({'LineId': lid, 'Content': f'unknown event {lid}',
                         'EventId': None, 'EventTemplate': None})
        else:
            content, template = TEMPLATES_C[eid]
            gt_c.append({'LineId': lid, 'Content': content,
                         'EventId': eid, 'EventTemplate': template})
        lid += 1

# Parser output: E4 gets extra text (correct grouping, wrong template text)
parsed_c = []
for row in gt_c:
    r = dict(row)
    if row['EventTemplate'] == 'alert [level=<*>] {msg=<*>}':
        r['EventTemplate'] = 'alert [level=<*>] {msg=<*>} extra'
    parsed_c.append(r)

# ============================================================
# Write all files
# ============================================================
for name, gt, parsed in [('system_a', gt_a, parsed_a),
                          ('system_b', gt_b, parsed_b),
                          ('system_c', gt_c, parsed_c)]:
    write_csv(f'/app/data/ground_truth/{name}.csv', gt, FIELDS)
    write_csv(f'/app/data/parser_output/{name}.csv', parsed, FIELDS)

print("Dataset generation complete.")
print(f"  system_a: {len(gt_a)} lines, ground_truth + parser_output")
print(f"  system_b: {len(gt_b)} lines, ground_truth + parser_output")
print(f"  system_c: {len(gt_c)} lines, ground_truth + parser_output")
