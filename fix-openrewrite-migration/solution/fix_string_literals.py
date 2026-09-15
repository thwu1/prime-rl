#!/usr/bin/env python3

"""
Selectively update javax → jakarta in string literals and non-import contexts,
and revert incorrect jakarta → javax for JDK-native packages.

Handles:
  - Forward: javax.servlet.* → jakarta.servlet.* (Jakarta EE)
  - Forward: javax.annotation.* → jakarta.annotation.* (Jakarta EE)
  - Forward: javax.validation.* → jakarta.validation.* (Jakarta EE)
  - Revert: jakarta.sql.* → javax.sql.* (JDK package — incorrectly migrated)
  - Preserve: javax.sql.* (JDK — do NOT change)
  - Preserve: javax.crypto.* (JDK — do NOT change)
"""

import glob
import re

# Jakarta EE packages: javax → jakarta in non-import contexts
MIGRATING_PACKAGES = [
    "servlet",
    "validation",
    "annotation",
    "inject",
    "persistence",
    "transaction",
    "ws.rs",
    "el",
    "enterprise",
    "json",
    "batch",
    "jms",
    "mail",
    "resource",
    "security.enterprise",
    "websocket",
    "faces",
    "activation",
    "xml.bind",
]

# JDK packages: jakarta → javax (revert over-migrations)
JDK_REVERT_PACKAGES = [
    "sql",
    "crypto",
    "net",
    "management",
]


def build_forward_pattern():
    """Build regex matching javax.{migrating_package} for forward migration."""
    alts = "|".join(re.escape(p) for p in MIGRATING_PACKAGES)
    return re.compile(r'javax\.(' + alts + r')(?=[\.\s"\';,\)\]\}]|$)')


def build_revert_pattern():
    """Build regex matching jakarta.{jdk_package} for reversion."""
    alts = "|".join(re.escape(p) for p in JDK_REVERT_PACKAGES)
    return re.compile(r'jakarta\.(' + alts + r')(?=[\.\s"\';,\)\]\}]|$)')


def fix_file(filepath, forward_pattern, revert_pattern):
    """Fix string literals in a file: forward-migrate and revert as needed."""
    with open(filepath, 'r') as f:
        content = f.read()

    original = content

    # Skip import lines — those are handled by fix_java_imports.py
    lines = content.split('\n')
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('import static '):
            fixed_lines.append(line)
            continue

        # Forward-migrate javax.{jakarta_ee} → jakarta.{jakarta_ee}
        line = forward_pattern.sub(r'jakarta.\1', line)

        # Revert incorrect jakarta.{jdk} → javax.{jdk}
        line = revert_pattern.sub(r'javax.\1', line)

        fixed_lines.append(line)

    new_content = '\n'.join(fixed_lines)

    if new_content != original:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"  Fixed string literals: {filepath}")
        return True
    return False


def main():
    forward_pattern = build_forward_pattern()
    revert_pattern = build_revert_pattern()
    fixed = 0

    print("Scanning Java source files for string-literal class references...")
    for java_file in sorted(glob.glob('/app/src/**/*.java', recursive=True)):
        if fix_file(java_file, forward_pattern, revert_pattern):
            fixed += 1

    print("Scanning properties files for class name values...")
    for props_file in sorted(glob.glob('/app/src/**/*.properties', recursive=True)):
        if fix_file(props_file, forward_pattern, revert_pattern):
            fixed += 1

    print(f"Post-migration fixup complete. Updated {fixed} file(s).")


if __name__ == '__main__':
    main()
