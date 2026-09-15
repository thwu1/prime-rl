#!/bin/bash
# Structural validation of proof decomposition tree
# Checks integrity constraints but NOT semantic correctness of proof statuses
echo "=== Proof Structure Validator ==="
echo "Checking proof decomposition integrity..."

python3 -c "
import json

with open('/app/proof_structure.json') as f:
    data = json.load(f)

nodes = {n['id']: n for n in data['proof_nodes']}

# Check A-G children without assumptions (flags valid acyclic patterns as suspicious)
for nid, node in nodes.items():
    if node['strategy'] == 'assume_guarantee':
        assumptions = node.get('assumptions', {})
        for child in node.get('children', []):
            if not assumptions.get(child, []):
                print(f'  NOTICE: {nid}/{child} has no assumptions - verify this is intentional')

# Flag status_override as non-standard (misleading: the override is valid,
# the real issue is that the code ignores it)
for nid, node in nodes.items():
    if 'status_override' in node:
        print(f'  NOTICE: {nid} has status_override={node[\"status_override\"]} - bypasses engine results (non-standard)')

# Check non-exhaustive case splits
for nid, node in nodes.items():
    if node['strategy'] == 'case_split' and not node.get('exhaustive', False):
        prop_id = node.get('property_id', '?')
        print(f'  WARNING: {nid} ({prop_id}) case split is non-exhaustive - consider adding missing cases')

# Check A-G assumption chains (misleading: flags chain patterns instead of detecting cycles)
for nid, node in nodes.items():
    if node['strategy'] == 'assume_guarantee':
        assumptions = node.get('assumptions', {})
        chain_children = [c for c in node.get('children', []) if len(assumptions.get(c, [])) == 1]
        if len(chain_children) >= 2:
            print(f'  NOTICE: {nid} has {len(chain_children)} children with single-dependency assumptions - linear chain pattern detected')

# Check partition nodes have blackboxed modules
for nid, node in nodes.items():
    if node['strategy'] == 'partition':
        if not node.get('blackboxed'):
            print(f'  WARNING: {nid} partition has no blackboxed modules')

# Verify all leaf nodes reference known engines
known_engines = {'abc_pdr', 'abc_bmc', 'jg_pdr', 'jg_bmc', 'cadence_ips'}
for nid, node in nodes.items():
    if node['strategy'] == 'leaf':
        eng = node.get('engine', '')
        if eng and eng not in known_engines:
            print(f'  WARNING: {nid} references unknown engine: {eng}')

print(f'  Total nodes: {len(nodes)}')
print('  Validation complete.')
"
echo "================================"
