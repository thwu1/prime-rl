#!/usr/bin/env python3
"""Apply targeted fixes to each bug in clab_processor.py."""

with open("/app/clab_processor.py") as f:
    code = f.read()

original = code

# Fix 1: Kind resolution must check group level (node > group > defaults)
old = (
    '            node_def.get("kind")\n'
    '            or defaults.get("kind")\n'
    '        )'
)
new = (
    '            node_def.get("kind")\n'
    '            or group_def.get("kind")\n'
    '            or defaults.get("kind")\n'
    '        )'
)
code = code.replace(old, new, 1)
assert code != original, "Fix 1 (kind resolution) failed to apply"
original = code

# Fix 2: Map merge order must be defaults -> kind -> group -> node
code = code.replace(
    'for source in (defaults, group_def, kind_def, node_def):',
    'for source in (defaults, kind_def, group_def, node_def):',
    1,
)
assert code != original, "Fix 2 (map merge order) failed to apply"
original = code

# Fix 3: Subnet capacity must subtract 3 (network + broadcast + gateway)
code = code.replace(
    'net.num_addresses - 2',
    'net.num_addresses - 3',
    1,
)
assert code != original, "Fix 3 (subnet capacity) failed to apply"
original = code

# Fix 4: Explicit IPs must be excluded from auto-allocation pool
code = code.replace(
    'reserved = {net.network_address, net.broadcast_address, gw}\n\n    # Auto-allocate',
    'reserved = {net.network_address, net.broadcast_address, gw}\n    reserved.update(explicit_ips)\n\n    # Auto-allocate',
    1,
)
assert code != original, "Fix 4 (explicit IP reservation) failed to apply"
original = code

# Fix 5: 3-tier CLOS must wire superspines to spines, not leaves
old_block = (
    '        for ss in range(1, num_superspines + 1):\n'
    '            for l in range(1, num_leaves + 1):\n'
    '                ss_if = next_iface(f"superspine{ss}")\n'
    '                l_if = next_iface(f"leaf{l}")\n'
    '                links.append({\n'
    '                    "endpoints": [\n'
    '                        f"superspine{ss}:{ss_if}",\n'
    '                        f"leaf{l}:{l_if}",\n'
    '                    ]\n'
    '                })'
)
new_block = (
    '        for ss in range(1, num_superspines + 1):\n'
    '            for s in range(1, num_spines + 1):\n'
    '                ss_if = next_iface(f"superspine{ss}")\n'
    '                s_if = next_iface(f"spine{s}")\n'
    '                links.append({\n'
    '                    "endpoints": [\n'
    '                        f"superspine{ss}:{ss_if}",\n'
    '                        f"spine{s}:{s_if}",\n'
    '                    ]\n'
    '                })'
)
code = code.replace(old_block, new_block, 1)
assert code != original, "Fix 5 (CLOS 3-tier wiring) failed to apply"
original = code

# Fix 6: Inventory hostname must include lab name
code = code.replace(
    'host_name = f"{prefix}-{name}"',
    'host_name = f"{prefix}-{lab_name}-{name}"',
    1,
)
assert code != original, "Fix 6 (inventory hostname) failed to apply"

with open("/app/clab_processor.py", "w") as f:
    f.write(code)

print("All 6 fixes applied successfully.")
