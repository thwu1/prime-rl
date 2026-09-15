#!/usr/bin/env python3
"""Bundle crash diagnostics into a compressed tar archive."""

import tarfile
import os

DEST = '/app/diagnostics.tar.gz'
SRC_DIR = '/tmp'

# Files to include in the bundle with their archive paths
entries = [
    (os.path.join(SRC_DIR, 'crash_report.json'), 'diagnostics/crash_state.json'),
    (os.path.join(SRC_DIR, 'page_format.md'),    'diagnostics/formats/page_store.md'),
    (os.path.join(SRC_DIR, 'system_info.txt'),   'diagnostics/system_info.txt'),
]

with tarfile.open(DEST, 'w:gz') as tar:
    for src_path, arcname in entries:
        tar.add(src_path, arcname=arcname)

print(f"Diagnostic bundle created at {DEST}")
