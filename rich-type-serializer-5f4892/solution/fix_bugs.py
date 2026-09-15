#!/usr/bin/env python3
"""
Analyze and fix all bugs in the rich-type serializer.

Identifies 7 bugs across 6 source files by tracing the serialize/deserialize
pipeline and applying targeted patches.
"""


import sys


def patch(filepath, old, new):
    """Read file, verify pattern exists, apply replacement, write back."""
    with open(filepath, 'r') as f:
        content = f.read()
    if old not in content:
        print(f"ERROR: Patch target not found in {filepath}", file=sys.stderr)
        print(f"  Looking for: {repr(old[:120])}", file=sys.stderr)
        sys.exit(1)
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"  Patched {filepath}")


print("Fixing Bug 1: escapeKey in pathstringifier.ts")
patch(
    '/app/src/pathstringifier.ts',
    r"key.replace(/\./g, '\\.')",
    r"key.replace(/\\/g, '\\\\').replace(/\./g, '\\.')",
)

print("Fixing Bug 2: walker dedupe in plainer.ts")
patch(
    '/app/src/plainer.ts',
    '    if (seen) {\n      return seen;\n    }',
    '    if (seen) {\n      return dedupe\n        ? { transformedValue: null }\n        : seen;\n    }',
)

print("Fixing Bug 3: root equality in plainer.ts")
patch(
    '/app/src/plainer.ts',
    '    const [representativePath, ...identicalPaths] = paths;\n'
    '    result[stringifyPath(representativePath)] = identicalPaths.map(stringifyPath);',
    '    const [representativePath, ...identicalPaths] = paths;\n'
    '\n'
    '    if (representativePath.length === 0) {\n'
    '      rootEqualityPaths = identicalPaths.map(stringifyPath);\n'
    '    } else {\n'
    '      result[stringifyPath(representativePath)] = identicalPaths.map(stringifyPath);\n'
    '    }',
)

print("Fixing Bug 4: setDeep Map traversal in accessDeep.ts")
patch(
    '/app/src/accessDeep.ts',
    '    } else if (isMap(parent)) {\n      const row = +key;',
    '    } else if (isMap(parent)) {\n'
    '      const isEnd = i === path.length - 2;\n'
    '      if (isEnd) {\n'
    '        break;\n'
    '      }\n'
    '      const row = +key;',
)

print("Fixing Bug 5: typed-array case in transformer.ts")
patch(
    '/app/src/transformer.ts',
    "      case 'custom':\n"
    "        return customRule.untransform(json, type, superJson);\n"
    "      default:",
    "      case 'custom':\n"
    "        return customRule.untransform(json, type, superJson);\n"
    "      case 'typed-array':\n"
    "        return typedArrayRule.untransform(json, type, superJson);\n"
    "      default:",
)

print("Fixing Bug 6: forEach skipping undefined values in util.ts")
patch(
    '/app/src/util.ts',
    'Object.entries(record).forEach(([key, value]) => {\n'
    '    if (value !== undefined) run(value, key);\n'
    '  });',
    'Object.entries(record).forEach(([key, value]) => run(value, key));',
)

print("Fixing Bug 7: meta version scoping in index.ts")
# Remove v: 1 from inside the annotations-only block
patch(
    '/app/src/index.ts',
    '        values: output.annotations,\n'
    '        v: 1,',
    '        values: output.annotations,',
)
# Add version setting after all meta blocks, before return
patch(
    '/app/src/index.ts',
    '    }\n\n    return res;\n  }',
    '    }\n\n    if (res.meta) res.meta.v = 1;\n\n    return res;\n  }',
)

print("\nAll 7 bugs fixed successfully.")
