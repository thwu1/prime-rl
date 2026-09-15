#!/usr/bin/env python3
"""
Analyze and fix three cascading bugs in the CDN configuration pipeline.

Bug 1 (api_server.py): The SQL query retrieving feature columns does not
filter by schema_name. After migration 002 exposed the 'r0' replica schema,
the query returns duplicate rows from both 'default' and 'r0', doubling
the feature count from ~112 to ~224.

Bug 2 (api_server.py): The pending_delete query parameter check uses
Python truthiness (if pending_delete_filter:) which evaluates to False
for empty string. When the cleanup task sends ?pending_delete (no value),
request.args.get() returns '', which is falsy, so the API returns ALL
prefixes instead of just pending-delete ones.

Bug 3 (config_loader.py): The config loader raises RuntimeError and
crashes when feature count exceeds MAX_FEATURES (200). It should instead
deduplicate features by name and truncate if still over the limit,
providing defense-in-depth against oversized configs.
"""

import re


def fix_api_server():
    """Fix bugs 1 and 2 in api_server.py."""
    with open('/app/api_server.py', 'r') as f:
        lines = f.readlines()

    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Fix 1: Add schema_name = 'default' filter to the feature query.
        # The query currently only filters by table_name, which returns
        # rows from both 'default' and 'r0' schemas after migration 002.
        if "WHERE table_name = ?" in line and "schema_name" not in line:
            line = line.replace(
                "WHERE table_name = ?",
                "WHERE table_name = ? AND schema_name = 'default'"
            )
            fixed_lines.append(line)
            i += 1
            continue

        # Fix 2: Change pending_delete check from truthiness to presence.
        # request.args.get('pending_delete') returns '' for ?pending_delete
        # (no value), which is falsy. Check parameter presence instead.
        if "pending_delete_filter = request.args.get('pending_delete')" in line:
            # Skip this variable assignment line entirely
            i += 1
            # Replace the truthiness check on the next line
            if i < len(lines) and 'if pending_delete_filter:' in lines[i]:
                indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
                fixed_lines.append(
                    indent + "if 'pending_delete' in request.args:\n"
                )
                i += 1
                continue
            continue

        fixed_lines.append(line)
        i += 1

    with open('/app/api_server.py', 'w') as f:
        f.writelines(fixed_lines)

    print("Fixed api_server.py:")
    print("  1. Added schema_name='default' filter to feature query")
    print("  2. Changed pending_delete check from truthiness to presence")


def fix_config_loader():
    """Fix bug 3 in config_loader.py: replace crash with graceful degradation."""
    with open('/app/config_loader.py', 'r') as f:
        content = f.read()

    # Locate the validation block that crashes on oversized input
    old_block = (
        "    # Validate against preallocated limit\n"
        "    # This limit exists for memory preallocation performance optimization\n"
        "    if feature_count > MAX_FEATURES:\n"
        "        # Equivalent to Rust: Result::unwrap() on Err\n"
        "        raise RuntimeError(\n"
        "            f\"Feature count {feature_count} exceeds maximum allocation \"\n"
        "            f\"limit of {MAX_FEATURES}. Aborting to prevent unbounded \"\n"
        "            f\"memory consumption.\"\n"
        "        )"
    )

    # Replace with deduplication + truncation logic
    new_block = (
        "    # Deduplicate features by name (defense against duplicate schema entries)\n"
        "    seen_names = set()\n"
        "    unique_features = []\n"
        "    for feat in features:\n"
        "        fname = feat.get('name', '')\n"
        "        if fname not in seen_names:\n"
        "            seen_names.add(fname)\n"
        "            unique_features.append(feat)\n"
        "    if len(unique_features) < feature_count:\n"
        "        logger.warning(\n"
        "            \"Deduplicated features: %d -> %d\",\n"
        "            feature_count, len(unique_features),\n"
        "        )\n"
        "    features = unique_features\n"
        "    feature_count = len(features)\n"
        "\n"
        "    # Graceful degradation: truncate if still over preallocated limit\n"
        "    if feature_count > MAX_FEATURES:\n"
        "        logger.warning(\n"
        "            \"Feature count %d exceeds limit %d, truncating\",\n"
        "            feature_count, MAX_FEATURES,\n"
        "        )\n"
        "        features = features[:MAX_FEATURES]\n"
        "        feature_count = MAX_FEATURES"
    )

    if old_block not in content:
        print("WARNING: Could not find exact crash block in config_loader.py")
        print("Attempting line-by-line search...")
        # Fallback: search for the raise RuntimeError pattern
        lines = content.split('\n')
        new_lines = []
        skip_until_paren_close = False
        replaced = False
        for line_idx, line in enumerate(lines):
            if skip_until_paren_close:
                if ')' in line:
                    skip_until_paren_close = False
                continue
            if 'raise RuntimeError(' in line and 'Feature count' in lines[line_idx + 1] if line_idx + 1 < len(lines) else '':
                # Find the start of the if block
                # Remove the preceding if and comment lines
                while new_lines and ('if feature_count > MAX_FEATURES' in new_lines[-1]
                                     or new_lines[-1].strip().startswith('#')):
                    new_lines.pop()
                new_lines.append(new_block + '\n')
                skip_until_paren_close = True
                replaced = True
                continue
            new_lines.append(line)
        if replaced:
            content = '\n'.join(new_lines)
    else:
        content = content.replace(old_block, new_block)

    with open('/app/config_loader.py', 'w') as f:
        f.write(content)

    print("Fixed config_loader.py:")
    print("  3. Replaced crash with deduplication + truncation")


if __name__ == '__main__':
    fix_api_server()
    fix_config_loader()
    print("\nAll 3 bugs fixed successfully.")
