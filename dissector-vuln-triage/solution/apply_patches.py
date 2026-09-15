#!/usr/bin/env python3
"""Analyze the NDP dissector source, write vulnerability report, and apply patches.

Reads per-instance challenge parameters to include the correct challenge token
in the vulnerability report.

This script:
  1. Extracts CHALLENGE_TOKEN from /app/src/ndp.h
  2. Writes /app/vulns.json with token + three identified vulnerabilities
  3. Patches src/ident.c  - adds bounds check to dissect_iface_name
  4. Patches src/auth.c   - fixes format string in process_auth_init
  5. Patches src/bulk.c   - adds bounds check to BULK_OVERWRITE handler
"""


import json
import os
import re

APP_DIR = '/app'
SRC_DIR = os.path.join(APP_DIR, 'src')


def load_challenge_token():
    """Read the challenge token from the source header."""
    ndp_h = os.path.join(SRC_DIR, 'ndp.h')
    with open(ndp_h) as f:
        content = f.read()
    match = re.search(r'#define\s+CHALLENGE_TOKEN\s+"([0-9a-f]+)"', content)
    if match:
        return match.group(1)
    # Fallback to config file
    config_path = os.path.join(APP_DIR, '.challenge.json')
    with open(config_path) as f:
        return json.load(f)['challenge_token']


def write_vulns_json():
    """Write the vulnerability analysis report with challenge token."""
    token = load_challenge_token()

    report = {
        "challenge_token": token,
        "vulnerabilities": [
            {
                "id": "VULN-001",
                "cwe": "CWE-121",
                "file": "src/ident.c",
                "function": "dissect_iface_name",
                "description": (
                    "Stack buffer overflow: interface name extension data is "
                    "copied byte-by-byte into a fixed-size stack buffer "
                    "(ident_name[IDENT_NAME_BUF]) without checking that the "
                    "input length fits. An oversized name overflows the buffer."
                ),
            },
            {
                "id": "VULN-002",
                "cwe": "CWE-134",
                "file": "src/auth.c",
                "function": "process_auth_init",
                "description": (
                    "Uncontrolled format string: when NDP_FLAG_DEBUG is set, "
                    "the user-supplied username is passed directly as the "
                    "format string to snprintf, allowing injection of format "
                    "specifiers such as %%n or %%s."
                ),
            },
            {
                "id": "VULN-003",
                "cwe": "CWE-787",
                "file": "src/bulk.c",
                "function": "handle_bulk",
                "description": (
                    "Out-of-bounds write: the BULK_OVERWRITE block handler "
                    "reads a user-controlled write_offset and copies data to "
                    "output + write_offset without verifying bounds."
                ),
            },
        ],
    }

    path = os.path.join(APP_DIR, 'vulns.json')
    with open(path, 'w') as f:
        json.dump(report, f, indent=2)
    print('Wrote %s' % path)


def patch_file(filepath, old, new, label):
    """Apply a single text replacement to a file."""
    with open(filepath, 'r') as f:
        content = f.read()
    assert old in content, \
        "Patch target not found in %s for %s" % (filepath, label)
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('Patched %s: %s' % (filepath, label))


def fix_ident():
    """Fix CWE-121: add bounds check before copying interface name."""
    patch_file(
        os.path.join(SRC_DIR, 'ident.c'),
        '    char ident_name[IDENT_NAME_BUF];\n\n'
        '    /* Copy name, normalizing underscore separators to hyphens */\n'
        '    size_t j = 0;',

        '    if (len >= IDENT_NAME_BUF) {\n'
        '        fprintf(stderr, "IDENT: interface name too long (%zu)\\n", len);\n'
        '        return -1;\n'
        '    }\n\n'
        '    char ident_name[IDENT_NAME_BUF];\n\n'
        '    /* Copy name, normalizing underscore separators to hyphens */\n'
        '    size_t j = 0;',

        'add length check before buffer copy',
    )


def fix_auth():
    """Fix CWE-134: use "%s" format specifier instead of raw username."""
    patch_file(
        os.path.join(SRC_DIR, 'auth.c'),
        'snprintf(log_msg, sizeof(log_msg), username);',
        'snprintf(log_msg, sizeof(log_msg), "%s", username);',
        'use %s format specifier for username',
    )


def fix_bulk():
    """Fix CWE-787: add bounds check before overwrite memcpy."""
    patch_file(
        os.path.join(SRC_DIR, 'bulk.c'),

        '                /* Copy data to output at the specified offset */\n'
        '                memcpy(output + write_offset, block_data + 4, write_len);',

        '                /* Copy data to output at the specified offset */\n'
        '                if ((size_t)write_offset + write_len > output_size) {\n'
        '                    fprintf(stderr, "BULK: overwrite offset out of bounds\\n");\n'
        '                    break;\n'
        '                }\n'
        '                memcpy(output + write_offset, block_data + 4, write_len);',

        'add bounds check on write_offset',
    )


if __name__ == '__main__':
    write_vulns_json()
    fix_ident()
    fix_auth()
    fix_bulk()
    print('All patches applied successfully.')
