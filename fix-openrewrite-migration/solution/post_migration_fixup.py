#!/usr/bin/env python3

"""
Post-migration fixup for patterns OpenRewrite's AST-based visitors do not handle.

OpenRewrite transforms Java import statements and type references in the AST,
but does NOT modify:
  - String literals containing fully-qualified class names
  - Property-file values referencing class names
  - Other non-Java-AST contexts

This script performs SELECTIVE replacement of javax.* -> jakarta.* only for
packages that migrated under Jakarta EE. JDK-bundled packages (javax.sql,
javax.crypto, javax.xml, javax.net, javax.management, etc.) are preserved.

The distinction is critical:
  - javax.servlet.*    -> jakarta.servlet.*     (Jakarta EE - MIGRATE)
  - javax.validation.* -> jakarta.validation.*  (Jakarta EE - MIGRATE)
  - javax.annotation.* -> jakarta.annotation.*  (Jakarta EE - MIGRATE)
  - javax.sql.*        -> javax.sql.*           (JDK - DO NOT MIGRATE)
  - javax.crypto.*     -> javax.crypto.*        (JDK - DO NOT MIGRATE)
"""

import glob
import re


# Jakarta EE packages that moved from javax.* to jakarta.*
# This list covers the packages relevant to Spring Boot migrations.
# JDK-bundled packages (javax.sql, javax.crypto, javax.xml, javax.net,
# javax.management, javax.security.auth, javax.sound, javax.swing, etc.)
# are intentionally excluded.
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
]


def build_pattern():
    """Build regex matching javax.{migrating_package} before a delimiter."""
    alts = "|".join(re.escape(p) for p in MIGRATING_PACKAGES)
    # Match javax. followed by a migrating package name, followed by a
    # boundary character (dot, quote, semicolon, space, paren, etc.)
    return re.compile(r'javax\.(' + alts + r')(?=[\.\s"\';,\)\]\}]|$)')


def fix_file(filepath, pattern):
    """Replace javax.{pkg} with jakarta.{pkg} for migrating packages only."""
    with open(filepath, 'r') as f:
        content = f.read()

    new_content = pattern.sub(r'jakarta.\1', content)

    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"  Fixed: {filepath}")
        return True
    return False


def main():
    pattern = build_pattern()
    fixed = 0

    # Fix remaining javax references in Java source files
    # (OpenRewrite handles imports but not string literals)
    print("Scanning Java source files for string-literal class references...")
    for java_file in sorted(glob.glob('/app/src/**/*.java', recursive=True)):
        if fix_file(java_file, pattern):
            fixed += 1

    # Fix property files with class name values
    print("Scanning properties files for class name values...")
    for props_file in sorted(glob.glob('/app/src/**/*.properties', recursive=True)):
        if fix_file(props_file, pattern):
            fixed += 1

    print(f"Post-migration fixup complete. Updated {fixed} file(s).")


if __name__ == '__main__':
    main()
