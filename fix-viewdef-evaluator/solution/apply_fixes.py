#!/usr/bin/env python3

"""
Apply targeted fixes to the SQL-on-FHIR ViewDefinition evaluator
and its FHIRPath helper layer.
"""

import sys

# ==== Fixes for evaluator.ts ====
EVALUATOR_PATH = "/app/src/evaluator.ts"

with open(EVALUATOR_PATH, "r") as f:
    content = f.read()

original = content

# --- Fix 1: forEachOrNull empty collection handling ---
old_1 = (
    "  let nodes = fhirpathEvaluate(node, selectExpr.forEachOrNull, def.constant, envVars);\n"
    "  return nodes.flatMap"
)
new_1 = (
    "  let nodes = fhirpathEvaluate(node, selectExpr.forEachOrNull, def.constant, envVars);\n"
    "  if (nodes.length === 0) {\n"
    "    nodes = [{}];\n"
    "  }\n"
    "  return nodes.flatMap"
)
content = content.replace(old_1, new_1, 1)
assert content != original, "Fix 1 (forEachOrNull) failed to apply"
after_fix1 = content

# --- Fix 2: recursiveTraverse should skip root node ---
old_2 = (
    "    result.push(currentNode);\n"
    "\n"
    "    paths.forEach"
)
new_2 = (
    "    if (!isRoot) {\n"
    "      result.push(currentNode);\n"
    "    }\n"
    "\n"
    "    paths.forEach"
)
content = content.replace(old_2, new_2, 1)
assert content != after_fix1, "Fix 2 (recursiveTraverse root) failed to apply"
after_fix2 = content

# --- Fix 3: handleColumn must handle collection:true ---
old_3 = (
    "    const vs = fhirpathEvaluate(node, c.path, def.constant, envVars);\n"
    "    if (vs.length <= 1) {"
)
new_3 = (
    "    const vs = fhirpathEvaluate(node, c.path, def.constant, envVars);\n"
    "    if (c.collection) {\n"
    "      record[c.name || c.path] = vs;\n"
    "    } else if (vs.length <= 1) {"
)
content = content.replace(old_3, new_3, 1)
assert content != after_fix2, "Fix 3 (collection flag) failed to apply"
after_fix3 = content

# --- Fix 4: handleRepeat must scope %rowIndex per node ---
old_4 = (
    "  return nodes.flatMap((n: any) => {\n"
    "    return handleSelect({ select: selectExpr.select }, n, def, envVars);\n"
    "  });"
)
new_4 = (
    "  return nodes.flatMap((n: any, index: number) => {\n"
    "    const childEnvVars = { ...envVars, rowIndex: index };\n"
    "    return handleSelect({ select: selectExpr.select }, n, def, childEnvVars);\n"
    "  });"
)
content = content.replace(old_4, new_4, 1)
assert content != after_fix3, "Fix 4 (repeat rowIndex) failed to apply"

with open(EVALUATOR_PATH, "w") as f:
    f.write(content)

print("All 4 evaluator fixes applied successfully", file=sys.stderr)

# ==== Fix for fhirpath-helper.ts ====
HELPER_PATH = "/app/src/fhirpath-helper.ts"

with open(HELPER_PATH, "r") as f:
    helper_content = f.read()

helper_original = helper_content

# --- Fix 5: processConstants must accept all value types, not just strings ---
old_5 = "if (key.startsWith('value') && typeof x[key] === 'string') {"
new_5 = "if (key.startsWith('value')) {"
helper_content = helper_content.replace(old_5, new_5, 1)
assert helper_content != helper_original, "Fix 5 (processConstants type filter) failed to apply"

with open(HELPER_PATH, "w") as f:
    f.write(helper_content)

print("Fix 5 (fhirpath-helper processConstants) applied successfully", file=sys.stderr)
