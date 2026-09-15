
"""Patch gitlib.py to use packfile_reader for pack-based object lookups."""

import re

GITLIB_PATH = '/app/gitlib.py'

with open(GITLIB_PATH, 'r') as f:
    content = f.read()

# The original code raises an exception when loose object lookup fails.
# Replace it with a call into packfile_reader.

old_block = (
    '    # Object not found in loose storage\n'
    '    raise Exception(f"Object {sha} not found")'
)

new_block = (
    '    # Fall through to packfile reading\n'
    '    from packfile_reader import find_and_read_from_packs\n'
    '    return find_and_read_from_packs(repo, sha)'
)

if old_block not in content:
    print("WARNING: Could not find the expected stub block in gitlib.py.")
    print("Attempting regex-based replacement...")
    # Fallback: replace any line that raises "Object ... not found"
    content = re.sub(
        r'    raise Exception\(f"Object \{sha\} not found.*"\)',
        '    from packfile_reader import find_and_read_from_packs\n'
        '    return find_and_read_from_packs(repo, sha)',
        content,
    )
else:
    content = content.replace(old_block, new_block)

with open(GITLIB_PATH, 'w') as f:
    f.write(content)

print(f"Patched {GITLIB_PATH} — packfile reading enabled.")
