#!/usr/bin/env python3
"""Fix incorrect expected values in the test manifest."""
import json

with open('/app/test_harness/manifest.json') as f:
    manifest = json.load(f)

for tc in manifest['test_cases']:
    if tc['id'] == 'case_14':
        # centroid out vs bare out (smooth default) IS a mismatch
        tc['expected'] = {
            'valid': False,
            'errors': [{'category': 'INTERPOLATION_MISMATCH', 'variable': 'vColor'}]
        }
    elif tc['id'] == 'case_15':
        # Both explicitly highp -- they match, no error
        tc['expected'] = {
            'valid': True,
            'errors': []
        }
    elif tc['id'] == 'case_16':
        # Different struct member names -- structural mismatch
        tc['expected'] = {
            'valid': False,
            'errors': [{'category': 'STRUCT_MISMATCH', 'variable': 'vSurface'}]
        }

with open('/app/test_harness/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print("Manifest corrections applied.")
