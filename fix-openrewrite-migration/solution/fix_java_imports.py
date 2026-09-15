#!/usr/bin/env python3

"""
Fix javax → jakarta imports in Java source files, and revert incorrect
jakarta → javax imports for JDK-native packages.

Two passes:
  1. Forward-migrate: javax.{jakarta_ee_package} → jakarta.{package}
     (servlet, validation, annotation, inject, persistence, xml.bind, etc.)
  2. Revert over-migrations: jakarta.{jdk_package} → javax.{package}
     (sql, crypto, net, management — these are JDK packages, not Jakarta EE)
"""

import glob

# Jakarta EE packages that moved from javax.* to jakarta.*
JAKARTA_EE_PREFIXES = [
    "javax.annotation.",
    "javax.validation.",
    "javax.servlet.",
    "javax.inject.",
    "javax.persistence.",
    "javax.transaction.",
    "javax.ws.rs.",
    "javax.enterprise.",
    "javax.json.",
    "javax.websocket.",
    "javax.faces.",
    "javax.el.",
    "javax.batch.",
    "javax.jms.",
    "javax.mail.",
    "javax.activation.",
    "javax.security.enterprise.",
    "javax.xml.bind.",
]

# JDK packages that must NEVER be jakarta.* — revert if incorrectly migrated
JDK_REVERT_PAIRS = [
    ("jakarta.sql.", "javax.sql."),
    ("jakarta.crypto.", "javax.crypto."),
    ("jakarta.net.", "javax.net."),
    ("jakarta.management.", "javax.management."),
]


def should_forward_migrate(import_line):
    """Check if a javax import should be migrated to jakarta."""
    for prefix in JAKARTA_EE_PREFIXES:
        if f"import {prefix}" in import_line or f"import static {prefix}" in import_line:
            return True
    return False


def should_revert(import_line):
    """Check if a jakarta import should be reverted to javax (JDK package)."""
    for jakarta_prefix, _ in JDK_REVERT_PAIRS:
        if f"import {jakarta_prefix}" in import_line or f"import static {jakarta_prefix}" in import_line:
            return True
    return False


def fix_imports(filepath):
    """Fix imports in a single Java file."""
    with open(filepath, 'r') as f:
        content = f.read()

    original = content
    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        if line.strip().startswith('import '):
            # Pass 1: Forward-migrate javax.{jakarta_ee} → jakarta.{jakarta_ee}
            if should_forward_migrate(line):
                for prefix in JAKARTA_EE_PREFIXES:
                    jakarta_prefix = "jakarta" + prefix[5:]  # javax.X → jakarta.X
                    line = line.replace(f"import {prefix}", f"import {jakarta_prefix}")
                    line = line.replace(f"import static {prefix}", f"import static {jakarta_prefix}")

            # Pass 2: Revert incorrect jakarta.{jdk} → javax.{jdk}
            if should_revert(line):
                for jakarta_prefix, javax_prefix in JDK_REVERT_PAIRS:
                    line = line.replace(f"import {jakarta_prefix}", f"import {javax_prefix}")
                    line = line.replace(f"import static {jakarta_prefix}", f"import static {javax_prefix}")

        fixed_lines.append(line)

    new_content = '\n'.join(fixed_lines)
    if new_content != original:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"  Fixed imports: {filepath}")
        return True
    return False


def main():
    fixed = 0
    print("Scanning Java source files for import fixes...")

    for java_file in sorted(glob.glob('/app/src/**/*.java', recursive=True)):
        if fix_imports(java_file):
            fixed += 1

    print(f"Fixed imports in {fixed} file(s).")


if __name__ == '__main__':
    main()
